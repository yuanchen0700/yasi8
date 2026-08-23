// opencode-sessions manager - zero-dependency local web server
// Acts as a thin client/proxy over the official `opencode serve` HTTP API.
// Reference: opencode-visualizer-cn (fork of vis) which talks to the same API.
//
// Why serve instead of reading the sqlite db directly:
//   - list / detail / rename use official REST endpoints (always fresh,
//     cross-directory, no sqlite lock contention)
//   - "continue conversation on the web" uses POST /session/:id/prompt_async
//     plus the /global/event SSE stream -> real streaming, no subprocess,
//     no codegraph-shutdown hang workaround.
//
// Usage: node server.js [ui-port]   (default ui-port 4123)

"use strict";

const http = require("node:http");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const crypto = require("node:crypto");
const { spawn } = require("node:child_process");

const PORT = parseInt(process.env.OCM_PORT || process.argv[2] || "4123", 10);
const SERVE_PORT = parseInt(process.env.OCM_SERVE_PORT || "4599", 10);
const SERVE_URL = `http://127.0.0.1:${SERVE_PORT}`;
const UI_PATH = path.join(__dirname, "index.html");
const VERSION = "2.0.0";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
};

// ------------------------------------------------------- opencode resolver

function toWindowsPath(p) {
  if (/^\/[a-zA-Z]\//.test(p)) {
    return p[1].toUpperCase() + ":" + p.slice(2).replace(/\//g, "\\");
  }
  return p.replace(/\//g, "\\");
}

function resolveOpencode() {
  const dirs = (process.env.PATH || "").split(path.delimiter).filter(Boolean);
  const cands = [];
  for (const d of dirs) {
    const win = toWindowsPath(d);
    cands.push(path.join(d, "node_modules", "opencode-ai", "bin", "opencode.exe"));
    cands.push(path.join(win, "node_modules", "opencode-ai", "bin", "opencode.exe"));
    cands.push(path.join(d, "opencode.exe"));
    cands.push(path.join(win, "opencode.exe"));
    cands.push(path.join(d, "opencode.cmd"));
    cands.push(path.join(win, "opencode.cmd"));
  }
  cands.push(path.join(os.homedir(), "AppData", "Roaming", "npm", "opencode.cmd"));
  for (const full of cands) {
    try {
      fs.accessSync(full);
      return full;
    } catch (_) {
      /* keep looking */
    }
  }
  return null;
}

function spawnOpencode(args, opts) {
  const oc = resolveOpencode();
  if (!oc) throw new Error("未找到 opencode 命令");
  if (oc.toLowerCase().endsWith(".exe")) {
    return spawn(oc, args, opts);
  }
  const line = `"${oc}" ${args.map((a) => `"${String(a).replace(/"/g, '""')}"`).join(" ")}`;
  return spawn(process.env.ComSpec || "cmd.exe", ["/d", "/s", "/c", line], opts);
}

// ----------------------------------------------------------- serve lifecycle

function isPortOpen(port, host) {
  return new Promise((resolve) => {
    const s = net.connect({ port, host }, () => {
      s.destroy();
      resolve(true);
    });
    s.on("error", () => resolve(false));
    s.setTimeout(800, () => {
      s.destroy();
      resolve(false);
    });
  });
}

async function serveHealthy() {
  try {
    const r = await fetch(`${SERVE_URL}/global/health`, { signal: AbortSignal.timeout(1500) });
    if (!r.ok) return false;
    const j = await r.json();
    return !!j.healthy;
  } catch (_) {
    return false;
  }
}

let serveStarted = false;
async function ensureServe() {
  if (await serveHealthy()) return true;
  if (serveStarted) return false;
  const oc = resolveOpencode();
  if (!oc) return false;
  try {
    spawnOpencode(["serve", "--port", String(SERVE_PORT), "--hostname", "127.0.0.1"], {
      detached: true,
      stdio: "ignore",
      windowsHide: true,
    }).unref();
    serveStarted = true;
  } catch (e) {
    console.error("[manager] failed to start opencode serve:", e.message);
    return false;
  }
  for (let i = 0; i < 30; i++) {
    await new Promise((r) => setTimeout(r, 500));
    if (await serveHealthy()) return true;
  }
  return false;
}

// ----------------------------------------------------- SSE broadcast (proxy)

// One persistent connection to opencode serve /global/event. Everything we
// receive is forwarded to every connected browser SSE client. The browser
// filters events by session id on its side.
const browserClients = new Set();

function broadcastToBrowsers(payloadJson) {
  const frame = `data: ${payloadJson}\n\n`;
  for (const res of browserClients) {
    try {
      res.write(frame);
    } catch (_) {
      browserClients.delete(res);
    }
  }
}

let serveEventConnecting = false;
async function connectServeEvents() {
  if (serveEventConnecting) return;
  serveEventConnecting = true;
  while (true) {
    if (!(await serveHealthy())) {
      await new Promise((r) => setTimeout(r, 2000));
      continue;
    }
    try {
      const r = await fetch(`${SERVE_URL}/global/event`, {
        headers: { Accept: "text/event-stream" },
      });
      if (!r.ok || !r.body) {
        await new Promise((res) => setTimeout(res, 2000));
        continue;
      }
      const reader = r.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      // eslint-disable-next-line no-constant-condition
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        for (const block of blocks) {
          if (!block.trim()) continue;
          const prefix = "data: ";
          if (!block.startsWith(prefix)) continue;
          const raw = block.slice(prefix.length).trim();
          if (!raw) continue;
          try {
            JSON.parse(raw); // validate
          } catch (_) {
            continue;
          }
          broadcastToBrowsers(raw);
        }
      }
    } catch (_) {
      /* connection dropped; loop will reconnect */
    }
    await new Promise((res) => setTimeout(res, 1500));
  }
}

// ----------------------------------------------------------- serve proxying

async function proxyToServe(method, servePath, { query, body, directory } = {}) {
  let url = `${SERVE_URL}${servePath}`;
  if (query && Object.keys(query).length) {
    const sp = new URLSearchParams();
    for (const [k, v] of Object.entries(query)) {
      if (v !== undefined && v !== null && v !== "") sp.set(k, String(v));
    }
    const qs = sp.toString();
    if (qs) url += `?${qs}`;
  }
  // Match the reference client (opencode-visualizer-cn opencode.ts): only set
  // Content-Type when there is a body, and never attach an AbortSignal for
  // ordinary calls. Over-eager headers/signals were a divergence worth removing.
  const headers = {};
  if (directory) headers["x-opencode-directory"] = directory;
  const init = { method, headers };
  if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    init.body = JSON.stringify(body);
  }
  let r;
  try {
    r = await fetch(url, init);
  } catch (e) {
    console.error("[proxy] fetch threw:", method, url, e && e.message);
    throw e;
  }
  const text = await r.text();
  let data = null;
  if (text.trim()) {
    try {
      data = JSON.parse(text);
    } catch (_) {
      data = text;
    }
  }
  if (!r.ok) {
    console.error(
      "[proxy] non-ok",
      "status=" + r.status,
      method,
      url,
      "len=" + text.length,
      "head=" + text.slice(0, 240)
    );
  }
  // IMPORTANT: callers branch on `r.ok`. The raw fetch Response has `.ok`,
  // but we must forward it; otherwise `r.ok` is undefined and every route
  // wrongly takes the error path (this was the original v2.0.0 bug).
  return { ok: r.ok, status: r.status, data };
}

// ------------------------------------------------------------------- http

// opencode serve's GET /session is SCOPED by the `directory` query param: it
// only returns sessions whose working directory lives under that path. The
// manager itself is launched from some project dir, so a bare listing only
// shows sessions for that one repo. To show ALL of the user's sessions we ask
// serve once per "root" directory and merge the results by session id.
//
// Roots we scan:
//   1. the user's home dir  (serve prefix-matches -> covers every C:\Users\Cheng session)
//   2. the git repo root of the manager's cwd (the repo we're running inside)
//   3. any nested git repos under that root (e.g. yasi/fun/rtk/rgk)
//   4. every working_dir recorded in the global session store's .meta files
//   5. OCM_SCAN_DIRS env (comma separated) for anything else
// Results are cached for 30s so repeated list refreshes don't re-walk disks.

let _rootsCache = { at: 0, roots: [] };

function findGitRoot(start) {
  let dir = start;
  for (let i = 0; i < 24; i++) {
    try {
      if (fs.existsSync(path.join(dir, ".git"))) return dir;
    } catch (_) {
      /* ignore */
    }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function scanNestedGitRoots(root, maxDepth) {
  const out = new Set();
  const walk = (dir, depth) => {
    if (depth > maxDepth) return;
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (_) {
      return;
    }
    for (const e of entries) {
      if (e.name === ".git") {
        out.add(dir);
        continue;
      }
      if (e.isDirectory() && e.name !== "node_modules" && !e.name.startsWith(".git")) {
        walk(path.join(dir, e.name), depth + 1);
      }
    }
  };
  walk(root, 0);
  return out;
}

function globalStoreRoots() {
  const roots = new Set();
  const store = path.join(os.homedir(), ".atomcode", "sessions");
  try {
    for (const proj of fs.readdirSync(store)) {
      const pd = path.join(store, proj);
      let stat;
      try {
        stat = fs.statSync(pd);
      } catch (_) {
        continue;
      }
      if (!stat.isDirectory()) continue;
      for (const f of fs.readdirSync(pd)) {
        if (!f.endsWith(".meta")) continue;
        try {
          const j = JSON.parse(fs.readFileSync(path.join(pd, f), "utf8"));
          if (j.working_dir) roots.add(j.working_dir);
        } catch (_) {
          /* ignore malformed meta */
        }
      }
    }
  } catch (_) {
    /* store missing -> nothing to add */
  }
  return roots;
}

function discoverRoots() {
  const now = Date.now();
  if (now - _rootsCache.at < 30000 && _rootsCache.roots.length) return _rootsCache.roots;
  const roots = new Set();
  roots.add(os.homedir());
  const gitRoot = findGitRoot(process.cwd());
  if (gitRoot) {
    roots.add(gitRoot);
    for (const n of scanNestedGitRoots(gitRoot, 5)) roots.add(n);
  }
  // Also ask serve for its OWN launch-repo scope (no directory param). This
  // catches nested-repo sessions (e.g. yasi/fun/rtk/rgk) that an exact
  // directory= query would miss, since serve's directory filter matches the
  // session's repo root precisely rather than prefix-matching.
  roots.add("");
  for (const r of globalStoreRoots()) roots.add(r);
  for (const e of (process.env.OCM_SCAN_DIRS || "").split(",")) {
    const t = e.trim();
    if (t) roots.add(t);
  }
  const list = [...roots];
  _rootsCache = { at: now, roots: list };
  return list;
}

function json(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, {
    "Content-Type": "application/json; charset=utf-8",
    "Cache-Control": "no-store",
  });
  res.end(body);
}

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, "http://localhost");
  const p = url.pathname;

  if (req.method === "GET" && p === "/api/health") {
    const healthy = await serveHealthy();
    return json(res, 200, {
      ok: true,
      serveHealthy: healthy,
      serveVersion: healthy ? (await proxyToServe("GET", "/global/health")).data?.version : null,
      serveUrl: SERVE_URL,
      opencode: resolveOpencode(),
      version: VERSION,
    });
  }

  // SSE stream of opencode events for the browser.
  if (req.method === "GET" && p === "/api/events") {
    res.writeHead(200, {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
    });
    res.write("retry: 2000\n\n");
    browserClients.add(res);
    const ping = setInterval(() => {
      try {
        res.write(": ping\n\n");
      } catch (_) {
        /* ignore */
      }
    }, 15000);
    req.on("close", () => {
      clearInterval(ping);
      browserClients.delete(res);
    });
    return;
  }

  if (req.method === "GET" && p === "/api/providers") {
    try {
      const r = await proxyToServe("GET", "/provider");
      if (!r.ok) return json(res, r.status, { error: "serve error", detail: r.data });
      return json(res, 200, r.data);
    } catch (e) {
      return json(res, 500, { error: e.message });
    }
  }

  if (req.method === "GET" && p === "/api/sessions") {
    try {
      const roots = discoverRoots();
      const limit = url.searchParams.get("limit") || "2000";
      const search = url.searchParams.get("search") || undefined;
      const byId = new Map();
      await Promise.all(
        roots.map(async (dir) => {
          const r = await proxyToServe("GET", "/session", {
            query: { limit, directory: dir, search },
          });
          if (r.ok && Array.isArray(r.data)) {
            for (const s of r.data) byId.set(s.id, s);
          }
        })
      );
      const sessions = [...byId.values()].sort(
        (a, b) => ((b.time && b.time.updated) || 0) - ((a.time && a.time.updated) || 0)
      );
      const totals = sessions.reduce(
        (a, s) => {
          a.messages += s.summary?.messages ?? 0;
          a.tokens += (s.tokens?.input || 0) + (s.tokens?.output || 0) + (s.tokens?.reasoning || 0);
          a.cost += s.cost || 0;
          return a;
        },
        { sessions: sessions.length, messages: 0, tokens: 0, cost: 0 }
      );
      return json(res, 200, { sessions, totals });
    } catch (e) {
      return json(res, 500, { error: e.message });
    }
  }

  // Create a brand-new session on serve. opencode requires a working
  // directory for a session; the client sends it, otherwise we fall back to
  // OCM_DEFAULT_DIR then the OS home dir. An optional title renames it.
  if (req.method === "POST" && p === "/api/sessions") {
    let bodyRaw = "";
    req.on("data", (c) => (bodyRaw += c));
    req.on("end", async () => {
      let payload = {};
      try {
        payload = bodyRaw ? JSON.parse(bodyRaw) : {};
      } catch (_) {
        /* ignore */
      }
      try {
        const directory =
          String(payload.directory || "").trim() ||
          process.env.OCM_DEFAULT_DIR ||
          os.homedir();
        const r = await proxyToServe("POST", "/session", {
          query: { directory },
          body: {},
        });
        if (!r.ok) return json(res, r.status, { error: "创建会话失败", detail: r.data });
        const created = (r.data && r.data.session) || r.data || {};
        const id = created.id;
        if (!id) return json(res, 502, { error: "serve 未返回会话 id", detail: created });
        if (payload.title && String(payload.title).trim()) {
          const title = String(payload.title).trim().slice(0, 200);
          try {
            const tr = await proxyToServe("PATCH", `/session/${id}`, {
              body: { title },
              directory,
            });
            if (tr.ok && tr.data) created.title = tr.data.title || title;
          } catch (_) {
            /* 标题设置失败不阻断创建 */
          }
        }
        return json(res, 200, { ok: true, session: created });
      } catch (e) {
        return json(res, 500, { error: e.message });
      }
    });
    return;
  }

  const detailMatch = p.match(/^\/api\/sessions\/([^/]+)$/);
  if (req.method === "GET" && detailMatch) {
    const id = decodeURIComponent(detailMatch[1]);
    try {
      const r = await proxyToServe("GET", `/session/${id}`, {
        query: { directory: url.searchParams.get("directory") || undefined },
      });
      if (!r.ok) return json(res, r.status, { error: "serve error", detail: r.data });
      return json(res, 200, r.data);
    } catch (e) {
      return json(res, 500, { error: e.message });
    }
  }

  const msgMatch = p.match(/^\/api\/sessions\/([^/]+)\/messages$/);
  if (req.method === "GET" && msgMatch) {
    const id = decodeURIComponent(msgMatch[1]);
    try {
      const r = await proxyToServe("GET", `/session/${id}/message`, {
        query: {
          directory: url.searchParams.get("directory") || undefined,
          limit: url.searchParams.get("limit") || "1000",
        },
      });
      if (!r.ok) return json(res, r.status, { error: "serve error", detail: r.data });
      return json(res, 200, { messages: Array.isArray(r.data) ? r.data : [] });
    } catch (e) {
      return json(res, 500, { error: e.message });
    }
  }

  const actionMatch = p.match(/^\/api\/sessions\/([^/]+)\/(\w+)$/);
  if (actionMatch && (req.method === "POST" || req.method === "PATCH")) {
    const id = decodeURIComponent(actionMatch[1]);
    const action = actionMatch[2];
    let bodyRaw = "";
    req.on("data", (c) => (bodyRaw += c));
    req.on("end", async () => {
      let payload = {};
      try {
        payload = bodyRaw ? JSON.parse(bodyRaw) : {};
      } catch (_) {
        /* ignore */
      }
      try {
        if (action === "title") {
          const title = String(payload.title || "").trim().slice(0, 200);
          if (!title) return json(res, 400, { error: "标题不能为空" });
          const r = await proxyToServe("PATCH", `/session/${id}`, {
            body: { title },
            directory: payload.directory,
          });
          if (!r.ok) return json(res, r.status, { error: "改名失败", detail: r.data });
          return json(res, 200, { ok: true, title });
        }
        if (action === "chat") {
          const text = String(payload.text || "").trim();
          // Inline image attachments arrive as data: URLs (or file:// URLs).
          // Only forward safe schemes; opencode rejects everything else anyway.
          // NOTE: opencode serve's prompt_async does NOT accept the
          // x-opencode-directory header and silently ignores a top-level
          // "files" array. Attachments must be encoded as regular message
          // parts of type "file" with {url, mime, name}.
          //
          // To avoid sending huge base64 blobs to opencode (which makes the
          // request slow / times out on big screenshots), data: URLs are
          // decoded to a temp file and re-referenced as a file:// path. opencode
          // reads the file itself, so the HTTP payload stays tiny.
          let files = [];
          if (Array.isArray(payload.files)) {
            const tmpDir = path.join(os.tmpdir(), "ocm-uploads");
            try { fs.mkdirSync(tmpDir, { recursive: true }); } catch (_) {}
            for (const f of payload.files.slice(0, 8)) {
              if (!f || typeof f.uri !== "string") continue;
              if (!/^(data:|file:\/\/)/i.test(f.uri)) continue;
              let url = f.uri;
              let mime = String(f.mime || "").slice(0, 100);
              if (/^data:/i.test(f.uri)) {
                const m = f.uri.match(/^data:([^;,]*)(?:;base64)?,(.*)$/s);
                if (!m) continue;
                const dataMime = m[1] || mime || "application/octet-stream";
                const buf = Buffer.from(m[2], "base64");
                const ext = (dataMime.split("/")[1] || "bin").split(";")[0];
                const fileName = `ocm-${Date.now()}-${crypto.randomBytes(4).toString("hex")}.${ext}`;
                const abs = path.join(tmpDir, fileName);
                try { fs.writeFileSync(abs, buf); } catch (_) { continue; }
                url = "file:///" + abs.split("\\").join("/");
                mime = dataMime;
              }
              files.push({
                url,
                mime,
                name: String(f.name || "").slice(0, 200),
              });
            }
          }
          if (!text && files.length === 0) {
            return json(res, 400, { error: "消息不能为空" });
          }
          // prompt_async requires model.providerID. Prefer the model the
          // client sends (resuming a session keeps its own model); otherwise
          // fall back to a known-good default so a fresh session without a
          // model can still be continued from the web. The default is the
          // user's active model on this machine; override via env if needed.
          const model =
            payload.model && payload.model.providerID
              ? payload.model
              : {
                  providerID: process.env.OCM_DEFAULT_PROVIDER || "zen2",
                  modelID: process.env.OCM_DEFAULT_MODEL || "deepseek-v4-flash-free",
                };
          const parts = [{ type: "text", text }];
          for (const f of files) {
            parts.push({ type: "file", url: f.url, mime: f.mime, name: f.name });
          }
          const body = {
            agent: payload.agent || "build",
            model,
            parts,
          };
          const r = await proxyToServe("POST", `/session/${id}/prompt_async`, {
            body,
          });
          if (!r.ok) return json(res, r.status, { error: "发送失败", detail: r.data });
          return json(res, 200, { ok: true });
        }
        return json(res, 404, { error: "未知操作" });
      } catch (e) {
        return json(res, 500, { error: e.message });
      }
    });
    return;
  }

  if (req.method === "GET" && p === "/") {
    let html = "";
    try {
      html = fs.readFileSync(UI_PATH, "utf8");
    } catch (_) {
      html =
        "<html><body><h1>index.html not found</h1><p>Put index.html next to server.js</p></body></html>";
    }
    res.writeHead(200, {
      "Content-Type": "text/html; charset=utf-8",
      "Cache-Control": "no-store",
    });
    return res.end(html);
  }

  json(res, 404, { error: "Not Found" });
});

server.on("error", (e) => {
  if (e.code === "EADDRINUSE") {
    console.error(`[manager] Port ${PORT} is already in use.`);
    console.error(`[manager] Try: node server.js <other-port>`);
  } else {
    console.error("[manager] server error:", e.message);
  }
  process.exit(1);
});

server.listen(PORT, "127.0.0.1", async () => {
  console.log(`[manager] UI ready at http://127.0.0.1:${PORT}`);
  console.log(`[manager] proxying opencode serve at ${SERVE_URL}`);
  console.log(`[manager] opencode: ${resolveOpencode() || "NOT FOUND"}`);
  const ok = await ensureServe();
  console.log(`[manager] opencode serve: ${ok ? "healthy" : "UNAVAILABLE"}`);
  if (ok) connectServeEvents();
});
