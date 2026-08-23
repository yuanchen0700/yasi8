# 网络访问问题排查报告：ZeroTier 无法访问 8996 服务

**日期**：2026-08-03
**问题**：通过 ZeroTier 访问本机 8996 端口服务（Python `server.py`）无效

---

## 一、排查结论

| 检查项 | 结果 | 说明 |
|--------|------|------|
| 8996 端口监听 | ✅ 正常 | 监听 `0.0.0.0:8996`（PID 23040，Python server.py），已绑定所有网卡 |
| ZeroTier 服务 | ✅ 运行中 | 9993 TCP/UDP 正常监听 |
| ZeroTier 网络接入 | ❌ 异常（已修复） | 网卡只有 169.254 假地址，未拿到管理 IP |
| 最终连通性 | ✅ 通过 | `10.110.218.198:8996` TCP 测试成功 |

**根因**：ZeroTier 网络配置文件 `C:\ProgramData\ZeroTier\One\networks.d\633e31d8a2357999.conf` 中 `allowManaged=0`，导致客户端拒绝应用控制器下发的管理 IP，接口地址停留在 APIPA（169.254.72.85），机器等于未真正接入网络。

---

## 二、排查步骤

1. **确认端口监听范围**
   ```powershell
   netstat -ano | Select-String "8996"
   Get-NetTCPConnection -LocalPort 8996   # → 0.0.0.0:8996 Listen, PID 23040
   ```
   服务已监听所有网卡（`0.0.0.0`），排除服务端绑定问题。

2. **确认进程身份**
   ```powershell
   Get-CimInstance Win32_Process -Filter "ProcessId=23040" | Select -ExpandProperty CommandLine
   # → python.exe server.py
   ```

3. **检查 ZeroTier 网卡 IP**
   ```powershell
   Get-NetIPAddress -InterfaceAlias "*ZeroTier*"
   # → 169.254.72.85（APIPA 自动分配地址，异常信号）
   ```

4. **读取网络配置定位根因**
   `networks.d\633e31d8a2357999.conf` 关键字段：
   ```
   allowManaged=0   ← 禁止应用控制器分配的 IP（根因）
   allowGlobal=0
   allowDefault=0
   ```

---

## 三、修复方案

```powershell
# 以管理员身份执行
zerotier-cli set 633e31d8a2357999 allowManaged=1
```

修复后结果：
- `allowManaged: true`
- `assignedAddresses: ["10.110.218.198/24"]`
- `status: OK`

验证：

```powershell
Get-NetIPAddress -InterfaceAlias "*ZeroTier*"   # → 10.110.218.198
Test-NetConnection 10.110.218.198 -Port 8996   # → TcpTestSucceeded: True
```

---

## 四、经验总结

1. **端口监听 vs 网络可达是两回事**：`0.0.0.0` 监听只保证服务绑定了所有网卡，不代表远端一定可达；排查时应先确认链路（VPN/虚拟网卡）本身是否正常。
2. **169.254.x.x（APIPA）是虚拟网卡故障的典型信号**：ZeroTier / WireGuard 等虚拟网卡拿不到分配 IP 时，通常表现为接口 IP 变成 169.254 段。
3. **ZeroTier 的 allowManaged 是常见坑**：重装或迁移配置后该字段可能为 0，导致设备"在线但没 IP"。可通过 `zerotier-cli listnetworks` 查看 assignedAddresses 为空来快速判断。
4. **常用排查命令**：
   ```powershell
   netstat -ano | Select-String "端口号"      # 查监听
   zerotier-cli status                        # 查服务状态
   zerotier-cli listnetworks                  # 查网络与分配 IP
   zerotier-cli peers                         # 查对端
   Test-NetConnection <IP> -Port <端口>       # 查连通性
   ```
