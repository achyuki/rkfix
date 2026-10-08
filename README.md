# RK R75PRO V2 电量显示修复
> 注：100% AIGC

修复在 [WebHID 驱动](https://drive.rkgaming.com/) 修改配置后，Fn+Enter 显示电量失效的 bug。

另见：
protocol.md(通信报文逆向文档)
fix.md(修复报告)

使用：
```shell
# USB wired
sudo python rkfix.py /dev/hidraw3
# 2.4G receiver
sudo python rkfix.py /dev/hidraw5 --dongle
```

预期输出：
```
sudo python fix.py --dongle /dev/hidraw2
[*] RK R75PRO V2 Fn+Enter battery fix, channel: 2.4G dongle (output/input report 19)
[*] opening /dev/hidraw2
[*] initial read: reading WIN/FN1 layer (504 bytes, layer 1 table 0)
[*] cmd=65: request sent, waiting for 504 bytes
[*] cmd=65: received 126/504 (25%)
[*] cmd=65: received 252/504 (50%)
[*] cmd=65: received 378/504 (75%)
[*] cmd=65: received 504/504 (100%)
[+] cmd=65: read complete, 504 bytes
[*] index 81 (row 3, col 13) holds 0x00000000, patching to 0x07000024
[*] cmd=1: writing 504 bytes in 36 packets
[*] cmd=1: acked 9/36 (25%)
[*] cmd=1: acked 18/36 (50%)
[*] cmd=1: acked 27/36 (75%)
[*] cmd=1: acked 36/36 (100%)
[+] cmd=1: write complete, 36 packets acknowledged
[*] verify: reading WIN/FN1 layer (504 bytes, layer 1 table 0)
[*] cmd=65: request sent, waiting for 504 bytes
[*] cmd=65: received 126/504 (25%)
[*] cmd=65: received 252/504 (50%)
[*] cmd=65: received 378/504 (75%)
[*] cmd=65: received 504/504 (100%)
[+] cmd=65: read complete, 504 bytes
[+] index 81 reads back 0x07000024
[+] done: Fn+Enter should show the battery level again on the Windows layout when not in wired mode.
```