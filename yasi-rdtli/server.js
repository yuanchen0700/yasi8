#!/usr/bin/env node
"use strict";

/*
 * 极简静态文件服务器（零依赖，低内存占用）
 * 用法：node server.js [端口] [目录]
 * 默认：端口 8030，目录 = 本文件所在目录
 * 特性：MIME 类型、目录 index.html、路径穿越防护、流式响应、HTML 组件预渲染缓存
 */

var http = require("http");
var fs = require("fs");
var path = require("path");

var PORT = parseInt(process.argv[2] || "8030", 10);
var ROOT = path.resolve(process.argv[3] || __dirname);

var MIME = {
  ".html": "text/html; charset=utf-8",
  ".htm": "text/html; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".mp3": "audio/mpeg",
  ".ogg": "audio/ogg",
  ".wav": "audio/wav",
  ".mp4": "video/mp4",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".gif": "image/gif",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".ico": "image/x-icon",
  ".woff": "font/woff",
  ".woff2": "font/woff2",
  ".ttf": "font/ttf",
  ".map": "application/json",
  ".txt": "text/plain; charset=utf-8",
  ".md": "text/markdown; charset=utf-8",
  ".pdf": "application/pdf"
};

function loadIndex(dir) {
  for (var name of ["index.html", "index.htm"]) {
    var p = path.join(dir, name);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

function sendError(res, code, msg) {
  res.writeHead(code, { "Content-Type": "text/plain; charset=utf-8" });
  res.end(msg);
}

function sendFile(res, filePath, stat) {
  var ext = path.extname(filePath).toLowerCase();
  var headers = {
    "Content-Type": MIME[ext] || "application/octet-stream",
    "Content-Length": stat.size,
    "Cache-Control": ext === ".mp3" ? "public, max-age=31536000, immutable" : "no-cache",
    "Accept-Ranges": "bytes"
  };
  res.writeHead(200, headers);
  var stream = fs.createReadStream(filePath);
  stream.pipe(res);
  stream.on("error", function() { res.destroy(); });
}

var server = http.createServer(function(req, res) {
  var urlPath = decodeURIComponent(req.url.split("?")[0]);
  if (urlPath === "/") urlPath = "/index.html";
  if (urlPath.indexOf("..") !== -1 || urlPath.indexOf("\0") !== -1) {
    sendError(res, 400, "Bad Request");
    return;
  }
  var filePath = path.join(ROOT, urlPath);
  if (filePath.indexOf(ROOT) !== 0) {
    sendError(res, 403, "Forbidden");
    return;
  }
  fs.stat(filePath, function(err, stat) {
    if (err) {
      sendError(res, 404, "404 Not Found: " + urlPath);
      return;
    }
    if (stat.isDirectory()) {
      var idx = loadIndex(filePath);
      if (idx) return sendFile(res, idx, fs.statSync(idx));
      sendError(res, 403, "Directory listing disabled");
      return;
    }
    sendFile(res, filePath, stat);
  });
});

server.listen(PORT, "0.0.0.0", function() {
  console.log("[server.js] static server on http://0.0.0.0:" + PORT + " root=" + ROOT);
});
