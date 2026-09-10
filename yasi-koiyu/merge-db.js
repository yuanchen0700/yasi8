#!/usr/bin/env node
// merge-db.js — 合并两个 brand9.db，只追加新用户，不覆盖已有数据
// 用法: node merge-db.js <源数据库> <目标数据库>
//   例如: node merge-db.js /path/to/other/brand9.db /opt/yasi-koiyu/brand9.db

'use strict';

const { DatabaseSync } = require('node:sqlite');
const fs = require('node:fs');

const srcPath = process.argv[2];
const dstPath = process.argv[3];

if (!srcPath || !dstPath) {
  console.error('用法: node merge-db.js <源数据库> <目标数据库>');
  process.exit(1);
}
if (!fs.existsSync(srcPath)) {
  console.error('源数据库不存在: ' + srcPath);
  process.exit(1);
}

const src = new DatabaseSync(srcPath);
const dst = new DatabaseSync(dstPath, { fileMustExist: true });

console.log('源数据库 : ' + srcPath);
console.log('目标数据库: ' + dstPath);

// 获取目标已有的用户 id
const dstUserIds = new Set(
  dst.prepare('SELECT id FROM users').iterate().map(r => r.id)
);
const srcUsers = src.prepare('SELECT id, username FROM users ORDER BY id').all();
console.log('源数据库有 ' + srcUsers.length + ' 个用户');

// 1. 合并 users
let newUserCount = 0;
for (const row of src.prepare('SELECT * FROM users').iterate()) {
  if (!dstUserIds.has(row.id)) {
    dst.prepare(
      'INSERT INTO users (id, username, pass_salt, pass_hash, created_at, email, role, parent_id, note, nickname, uuid, link_open, login_token) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)'
    ).run(
      row.id, row.username, row.pass_salt, row.pass_hash, row.created_at,
      row.email || null, row.role, row.parent_id, row.note, row.nickname,
      row.uuid, row.link_open, row.login_token
    );
    newUserCount++;
  }
}
console.log('users: 新增 ' + newUserCount + ' 个（跳过 ' + (srcUsers.length - newUserCount) + ' 个已有）');

// 2. 合并 membership（只追加新用户的）
let newMemCount = 0;
for (const row of src.prepare('SELECT * FROM membership').iterate()) {
  if (!dstUserIds.has(row.user_id)) {
    dst.prepare(
      'INSERT INTO membership (user_id, key_type, key_start, key_expires, gold, streak, yd_level, last_status_day, updated_at, grace_days, last_day_reward) VALUES (?,?,?,?,?,?,?,?,?,?,?)'
    ).run(
      row.user_id, row.key_type, row.key_start, row.key_expires, row.gold,
      row.streak, row.yd_level, row.last_status_day, row.updated_at,
      row.grace_days, row.last_day_reward
    );
    newMemCount++;
  }
}
console.log('membership: 新增 ' + newMemCount + ' 条');

// 3. 合并 user_state（只追加新用户的）
let newStateCount = 0;
for (const row of src.prepare('SELECT * FROM user_state').iterate()) {
  if (!dstUserIds.has(row.user_id)) {
    dst.prepare(
      'INSERT OR IGNORE INTO user_state (user_id, key, value, updated_at) VALUES (?,?,?,?)'
    ).run(row.user_id, row.key, row.value, row.updated_at);
    newStateCount++;
  }
}
console.log('user_state: 新增 ' + newStateCount + ' 条');

// 4. 合并 email_codes（只追加未过期的）
let newCodeCount = 0;
const now = Math.floor(Date.now() / 1000);
for (const row of src.prepare('SELECT * FROM email_codes WHERE expires_at > ?').iterate(now)) {
  dst.prepare(
    'INSERT OR IGNORE INTO email_codes (email, code, sent_at, expires_at) VALUES (?,?,?,?)'
  ).run(row.email, row.code, row.sent_at, row.expires_at);
  newCodeCount++;
}
console.log('email_codes: 新增 ' + newCodeCount + ' 条（仅未过期）');

// 5. 合并 vip_keys（只追加未使用的）
let newVipCount = 0;
for (const row of src.prepare('SELECT * FROM vip_keys WHERE used_by IS NULL').iterate()) {
  dst.prepare(
    'INSERT OR IGNORE INTO vip_keys (code, type, used_by, used_at, created_by, created_at) VALUES (?,?,?,?,?,?)'
  ).run(row.code, row.type, row.used_by, row.used_at, row.created_by, row.created_at);
  newVipCount++;
}
console.log('vip_keys: 新增 ' + newVipCount + ' 条（仅未使用）');

src.close();
dst.close();
console.log('\n合并完成！');
