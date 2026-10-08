# RK 键盘 WebHID 驱动通信协议 API 文档

> 本文档由对 RK 官方网页驱动（WebHID 版）vite 打包产物 `bundle.js` 的完整逆向分析得出。
> 覆盖 BeiYing（北影）协议族全部 33 个键盘家族、2.4G Dongle 通道、USB 有线通道，
> 以及 TLW / QiWang / SparkLink / Gcome / JuPeng / HangSheng / RongYuan / Bytech / QMK
> 等其余协议族的结构性描述。
>
> 文档中的字节序除特别说明外均为小端（LE）。帧示意图中的数字均为十进制（另有标注除外）。

---

## 目录

1. [设备发现与识别](#1-设备发现与识别)
2. [传输模型与通道](#2-传输模型与通道)
3. [BeiYing 19 字节帧（2.4G Dongle 通道）](#3-beiying-19-字节帧24g-dongle-通道)
4. [BeiYing 519 字节帧（USB 有线通道）](#4-beiying-519-字节帧usb-有线通道)
5. [命令表](#5-命令表)
6. [boardProfile（128 字节板载配置）](#6-boardprofile128-字节板载配置)
7. [ledEffect（420 字节灯效参数）](#7-ledeffect420-字节灯效参数)
8. [ledColors（378 字节单键颜色）](#8-ledcolors378-字节单键颜色)
9. [keyMatrix（504 字节键矩阵）](#9-keymatrix504-字节键矩阵)
10. [宏（4096 字节宏区）](#10-宏4096-字节宏区)
11. [键码体系](#11-键码体系)
12. [灯效模式枚举与参数语义](#12-灯效模式枚举与参数语义)
13. [Dongle 密码 / 状态 / 主动上报](#13-dongle-密码--状态--主动上报)
14. [恢复出厂](#14-恢复出厂)
15. [家族变体表](#15-家族变体表)
16. [其余协议族](#16-其余协议族)
17. [WebHID 与 hidapi 的对应关系](#17-webhid-与-hidapi-的对应关系)
18. [实现注意点](#18-实现注意点)

---

## 1. 设备发现与识别

驱动通过 `navigator.hid.requestDevice({ filters: [...] })` 弹出选设备对话框，过滤器由设备表
`VE` 全量生成：每个条目 `{ vendorId, productId }`，QMK 协议条目额外带 `usagePage/usage`。
选择后按下表匹配：

| 判断条件 | 含义 |
|---|---|
| `vendorId == 表项.vendorId && productId == 表项.productId` | 基础匹配 |
| HID collection（含子 collection）中存在 `usagePage == 表项.usagePage && usage == 表项.usage` | 接口匹配 |
| Gcome 协议额外要求 `productName.trim().toLowerCase() == 表项.name.toLowerCase()` | 名称精确匹配 |

### 1.1 核心标识

| 常量 | 值 | 说明 |
|---|---|---|
| RK 键盘主 VID | **0x258A**（9610） | BeiYing 键盘几乎全用这个 |
| 2.4G 接收器 VID | 0x3554（13652） | 部分型号的 Dongle（如 R87PRO、M87、L75、M65 等） |
| USB 接口 usagePage/usage | **0xFF00 / 1**（另有 8 款用 0xFF02 / 1） | 有线键盘协议接口。0xFF02/1 的型号：RK-L98、RK R98PRO、RK X87、RK-A70、RK R98PRO V2、RK R108PRO、RK R75PRO V2 |
| Dongle 接口 usagePage/usage | **0xFF02 / 2**（少数鼠标形态用 0xFF00 / 1） | 2.4G 协议接口 |
| QMK 接口 | 0xFF00 / 1（个别不同） | 走 VIA 兼容协议 |

USB 与 Dongle 是同一型号的两条设备定义（`connectType: It.USB / It.Dongle`），
协议相同但通道与 cmdId 集合不同（见 §3/§4/§5）。

### 1.2 支持设备概况

- **BeiYing 键盘**：33 个家族、约 180 个设备定义（含地区变体）。型号覆盖：
  R87PRO、R87PRO RF、M87、L75、CB75-keyboard、CB68-keyboard、M65、M70、L98、N99、
  R98PRO、S98、F99、X87、K99、A70、A72、R75 JP、R65、S104、S85、M100、Ultra65、84、
  68、N80、As68、S70、M75、R98PRO V2、R108PRO、R75PRO V2 等。
- **BeiYing 鼠标**：M3、M30、K3、MG5、MO1、MO3（协议与键盘不同，见 §16）。
- **其余协议族**：TLW（CB75 鼠标）、QiWang（键盘 MG6 Pro、鼠标 5391K 等）、
  SparkLink（C68 等 21 款）、Gcome（K99/R87ProV2/R99/T87/T98）、JuPeng、HangSheng、
  RongYuan（A72-HE）、Bytech、QMK。
- 完整设备表（名称/vid/pid/接口/家族）见 `devices.json`（由 bundle 设备表自动提取）。

---

## 2. 传输模型与通道

### 2.1 三种通道

| 通道 | 连接方式 | HID 接口 | 报文形式 |
|---|---|---|---|
| USB 有线 | 键盘直连 | usagePage 0xFF00 / usage 1 | **feature report**（request-response 同步），519 字节大帧，reportId 6 或 9 |
| 2.4G Dongle | 接收器插入 | usagePage 0xFF02 / usage 2 | **output report 下发**（reportId 19）+ **input report 回包/主动上报**（reportId 19），19 字节小帧分包 |
| As68/S70 特例 | USB 直连 | 0xFF00 / 1 | 优先 output report 9，退化为 feature report 9（见 §15.3） |

网页驱动的 Web Worker（`communication` / `dongleCommunication`）只负责**节流、排队、
超时重试**，所有报文构造与解析都在主线程。用 Python 复刻时直接用同步收发 + 小延时即可。

### 2.2 板载槽（board）

帧中的 `board` 字段（2 位或 4 位）选择板载配置槽。**驱动实际始终传 0**（设备端只使用槽 0；
PC 端"多个配置文件"只是 localStorage 里的本地快照，写入设备时都落到槽 0）。

### 2.3 层（layer）与表（table）

| 枚举 | 值 | 含义 |
|---|---|---|
| layer: Nomal / FN1 / FN2 / Tap | 0 / 1 / 2 / 3 | 键矩阵层。Tap 层是"轻击层"（TapDelay 字段控制，见 §6） |
| table: WIN / MAC | 0 / 1 | 键矩阵表（Win/Mac 两套布局） |

键矩阵读写必须同时指定 `(layer, table)`；灯效与 profile 不分 layer/table。

---

## 3. BeiYing 19 字节帧（2.4G Dongle 通道）

### 3.1 帧布局（19 字节，不含 reportId；reportId = 19 = 0x13）

```
偏移  0    1             2              3                                4 .. 17    18
     ┌────┬─────────────┬──────────────┬───────────────────────────────┬──────────┬────┐
     │cmdId│pkgNum(bit0-6)│pkgIdx(bit0-6)│len(bit0-3) │board/layer/block │  payload │CRC │
     │     │retry(bit7)  │table(bit7,键 │(bit4-7 依命令)                  │ (≤14B)   │    │
     │     │             │矩阵命令专用)   │                                │          │    │
     └────┴─────────────┴──────────────┴───────────────────────────────┴──────────┴────┘
```

- `byte0` = cmdId（见 §5.1）
- `byte1` = `0x7F & packageNum`（本数据包分包总数）；**响应中 bit7 = 重发标志**
- `byte2` = `0x7F & packageIndex`（当前包序号）；**Get/SetKeyMatrix 时 bit7 = table**
- `byte3` 低 4 位 = 本包 payload 长度（≤14）；高 4 位：
  - 键矩阵命令：`bit4-5 = layer`、`bit6-7 = board`
  - 宏命令（Get/SetMacros）：`bit4-7 = block`（512B 块序号）
  - 其余命令：`bit4-7 = board`
- `byte4..17` = payload，每包最多 14 字节（BK=14）
- `byte18` = CRC：`(19 + Σ) & 0xFF`（初值 19）。**覆盖范围随家族不同**：
  26 个家族覆盖 `byte[0..17]`；iKe 家族（RK-R87PRO dongle）覆盖 `byte[0..16]`
  （即少算 payload 最后一字节；byte17 为 0 时两者等价）。

### 3.2 分包与 ACK 流程

**SET（下行）**：`packageNum = ceil(len/14)`，逐包发送；每发一包等一个 ACK：

```
发送包 i ──► 键盘回 input report（reportId 19）
                byte1 bit7 == 0 → 包被接受，发下一包
                byte1 bit7 == 1 → 要求重发本包（重试上限 10 次，SR=10）
```

**GET（上行）**：发一包零载荷请求（`pkgNum=1, pkgIdx=0, len=0`）；
键盘**连续回吐全部 input report**（每包 14 字节），逐包拼接成完整 payload。
响应包 `byte3` 低 4 位是实际长度，最后一包可以不满 14 字节。
若响应包 bit7=1 则重发请求。

GetMacros 例外：按块请求，8 块 × 512B。请求帧 `byte3 高4位=block`、`byte4=2`、`byte5=0`；
读完一块（37 包 ≈ 512/14）再请求下一块。

### 3.3 无响应帧拼接的参考实现要点

- 响应 input report 的 `byte1 & 0x7F` 是总包数、`byte2 & 0x7F` 是包序号；
  依序号拼 `byte4..4+len`。
- 主动上报（cmdId 10）会混在 input report 流里，按 `byte0` 区分。
- 网页驱动经 `dongleCommunication` worker 节流；Python 实现建议包间延时 ≥ 5ms。

---

## 4. BeiYing 519 字节帧（USB 有线通道）

### 4.1 请求帧（sendFeatureReport，519 字节，不含 reportId）

```
偏移  0      1                   2                   3    4             5       6       7 .. 518
     ┌──────┬───────────────────┬───────────────────┬─────┬────────────┬───────┬───────┬──────────┐
     │cmdId │ 视命令而定          │ 视命令而定          │ 1   │ 视命令而定   │len&0xFF│len>>8 │ payload  │
     └──────┴───────────────────┴───────────────────┴─────┴────────────┴───────┴───────┴──────────┘
```

| cmdId | byte1 | byte2 | byte4 |
|---|---|---|---|
| 130（取固件版本） | cmdVal=1 | 0 | 0 |
| 131/3（键矩阵 GET/SET） | `cmdVal \| (table<<2) \| layer` | board | 0 |
| 132/4（profile GET/SET） | 0 | cmdVal=board | 0 |
| 133（GetMacros） | 0 | cmdVal=board | **block 序号 0..7** |
| 5（SetMacros） | 0 | 0 | packageIndex（byte3=packageNum） |
| 134/6（灯色 GET/SET） | 0 | cmdVal=board | 0 |
| 138/10（灯效 GET/SET） | 0 | cmdVal=board | 0 |
| 17（恢复出厂） | cmdVal=0 | 0 | 0 |

- `byte3` 恒为 1（仅 SetMacros 例外，写 packageNum）。
- `byte5/6` = dataLength 小端：profile=128、键矩阵=504、宏=512、灯色=378、灯效=420、版本=10、出厂=1。
- payload 从 `byte7` 起，最大 512 字节。
- 帧总是完整 519 字节发送（padding 补 0）。

### 4.2 响应帧（receiveFeatureReport）

**WebHID 返回的数据首字节是 reportId**，之后是响应帧。响应帧比请求多 1 字节头：

```
resp[0]        = reportId
resp[1]        = 0 / 状态（未使用）
resp[2]        = cmdId 回显
resp[3]        = cmdVal
resp[4]        = 1
resp[5]        = packageNum（总包数）
resp[6]        = packageIndex
resp[7..8]     = dataLength 小端
resp[9..]      = payload
```

即 **payload 落在 resp 偏移 9**（相对去掉 reportId 的帧是偏移 8）。
解析时先按 `dataLength`（resp[7]|resp[8]<<8）截取 payload。

- GetMacros：8 次请求（byte4=0..7），每次回 512 字节，拼接成 4096 字节宏区。
- SetMacros：`packageNum = ceil(len/512)`，逐包发送，每包 `byte3=packageNum, byte4=packageIndex`。
- 写命令（SET）无 ACK：网页驱动经 worker 排队逐个发；Python 实现发完即可，
  建议包间延时 ≥ 10ms。
- GetProfile/GetKeyMatrix/GetLedColors/GetLedEffect 都是单帧请求/单帧响应。
- 取固件版本（cmd 130）：响应 payload 第 8、9 字节（resp 偏移 16、17）拼 hex 字符串，
  如 `0x01,0x02 → "0102"`。

---

## 5. 命令表

### 5.1 Dongle 通道（19 字节帧，枚举 `lv`）

| cmdId | 名称 | 方向 | payload 长度 |
|---|---|---|---|
| 1 | SetKeyMatrix | 下行 | 504 |
| 2 | SetLedColors | 下行 | 378 |
| 3 | SetMacros | 下行 | ≤4096，512B/块 |
| 4 | SetProfile | 下行 | 128 |
| 5 | GetPassword | 上行 | 10 |
| 6 | SetFactory（恢复出厂） | 下行 | 0 |
| 7 | GetDongleStatus | 上行 | 1 |
| 9 | SetLedEffect | 下行 | 420 |
| 10 | ActivelyReport | 主动上报 | — |
| 65 | GetKeyMatrix | 上行 | 504 |
| 66 | GetLedColors | 上行 | 378 |
| 67 | GetMacros | 上行 | 512/块 × 8 |
| 68 | GetProfile | 上行 | 128 |
| 73 | GetLedEffect | 上行 | 420 |

规律：`GET = SET | 0x40`（如 SetProfile 4 → GetProfile 68）。

### 5.2 USB 通道（519 字节帧）

| cmdId | 名称 | 方向 | payload | Dongle 对应 |
|---|---|---|---|---|
| 3 | SetKeyMatrix | 下行 | 504 | 1 |
| 4 | SetProfile | 下行 | 128 | 4 |
| 5 | SetMacros | 下行 | 512/块 | 3 |
| 6 | SetLedColors | 下行 | 378 | 2 |
| 10 | SetLedEffect | 下行 | 420 | 9 |
| 12 | SetTftPic 帧数据 | 下行 | 屏显图片分包（10 个家族） | — |
| 13 | SetTftPic 控制 | 下行 | 5 | — |
| 17 | SetFactory | 下行 | 1 | 6 |
| 18 | SetWebKeyTab | 下行 | 网页快捷键字符串（7 个家族） | — |
| 130 | GetPassword/固件版本 | 上行 | 10 | 5 |
| 131 | GetKeyMatrix | 上行 | 504 | 65 |
| 132 | GetProfile | 上行 | 128 | 68 |
| 133 | GetMacros | 上行 | 512/块 × 8 | 67 |
| 134 | GetLedColors | 上行 | 378 | 66 |
| 138 | GetLedEffect | 上行 | 420 | 73 |

规律：`GET = SET | 0x80`（SetProfile 4 → 132，SetLedEffect 10 → 138）。
**注意同一功能在 USB 与 Dongle 的 SET cmdId 数值不同**（键矩阵 3 vs 1、灯色 6 vs 2、
灯效 10 vs 9、宏 5 vs 3），必须分表。

### 5.3 TFT 小屏图片（cmd 12/13，仅 M87/S98/S104/S85/M100/Ultra65/84/N80/As68/S70）

- cmd 12 帧数据：分色块推送，byte4 = 整包字节和 & 255。
- cmd 13 控制包：`dataLength=5`，payload `byte0=mode<<6, byte1=frameNum, byte3=delay&255, byte4=delay>>8`；
  mode：0=结束、1=开始、2=停止。

---

## 6. boardProfile（128 字节板载配置）

一次 Get/SetProfile 读写整块 128 字节。块内是字段直排，最后两字节固定 `0x5A 0xA5` 哨兵。

### 6.1 家族 A 字段表（`v0` 枚举，覆盖 R87PRO/S98/M75/M87 等绝大多数型号）

| 偏移 | 字段 | 默认 | 取值语义 |
|---|---|---|---|
| 0 | Profile | 0 | 当前板载槽（驱动只用 0） |
| 1 | ReportRate | 3 | 0=125Hz 1=250Hz 2=500Hz 3=1000Hz |
| 2 | （保留） | 3 | 疑为 profile 总数 |
| 3 | Debounce | 3 | UI 两档：0=游戏模式，3=办公模式 |
| 4 | （保留） | 0 | |
| 5 | LedParameterType | 0 | 0=每模式独立灯效参数（读 §6.2 区），非 0=用全局 6/7/8 字段 |
| 6 | LedBrightness | 4 | 全局亮度，存储 0..19（UI 显示 = 值+1，1..20） |
| 7 | LedSpeed | 4 | 全局速度 0..4（UI 1..4） |
| 8 | LedColor | 7 | 0=纯色，7=混色（七彩） |
| 9 | LedModeSelection | 0 | 1=使用自定义灯效（LedMode=SelfDefine） |
| 10 | LedMode | 11 | 当前灯效（pt 枚举，§12） |
| 11 | LedGameMode | 32 | 游戏模式灯效位域 |
| 12 | （保留） | 1 | |
| 13 | WirelessChannel | 0 | 2.4G 信道 |
| 14 | KbConnectMode | 0 | 连接模式 |
| 15 | WinLock | 0 | Win 键锁（由键盘 Fn 键切换，PC 端只读） |
| 16 | KeyLock | 0 | 全键锁 |
| 17 | WASDSwitch | 0 | WASD↔方向键互换 |
| 18 | LogoMode | 0 | Logo 灯效（同 pt） |
| 19 | LogoColor | 0 | Logo 颜色 |
| 20 | LogoBrightness | 4 | Logo 亮度 |
| 21 | LogoSpeed | 4 | Logo 速度 |
| 22 | TapDelay | 0 | **Tap 层配置**：bit0=启用，bit1-7=层号(1..127)。不是延时！ |
| 23 | （保留） | 255 | |
| 24 | SleepTime | 10 | **睡眠时间 = 分钟 × 2**；0=永不休眠；默认 10 = 5 分钟 |
| 25 | （保留） | 0 | |
| 26 | LedModeMemery | 0 | 记忆灯效 |
| 27 | Logo2Mode | 0 | 第二 Logo 灯效 |
| 28..55 | （保留） | 0 | 其中 31/32 默认 3 |
| 56..91 | 每模式灯效参数 | 见 §6.2 | 17 个模式 × 2 字节 |
| 92..125 | （保留） | 0 | |
| 126/127 | 哨兵 | 90/165 | 固定 0x5A 0xA5 |

### 6.2 每模式灯效参数区（偏移 `56 + 2n`，n = 灯效模式号，0..17）

```
byte[56+2n]   = brightness（0..19，UI 显示 = 值+1；0xFF 表示该槽未使用）
byte[56+2n+1] = (speed << 4) | color     speed 0..4；color: 0=纯色, 7=混色
```

出厂默认：n=0（OFF）为 `255,255`；n=1..19 为 `20,71`（亮度20、速度4、混色）。

### 6.3 家族 B（R87PRO RF 系，`m0` 枚举）偏移差异

| 字段 | 偏移（家族 A → B） | | 字段 | 偏移（A → B） |
|---|---|---|---|---|
| ReportRate | 1 → 1 | | LedMode | 10 → **33** |
| Debounce | 3 → **2** | | LedColor | 8 → 34 |
| TapDelay | 22 → **8** | | LedBrightness | 6 → 35 |
| SleepTime | 24 → **9** | | LedSpeed | 7 → 36 |
| WinLock | 15 → 11 | | LogoMode/Color/Brightness/Speed | 18-21 → 37-40 |
| KeyLock | 16 → 12 | | Logo2Mode | 27 → 41 |
| WASDSwitch | 17 → 17 | | LedParameterType | 5 → 32 |
| 每模式参数区 | 56 → **83**（0..20） | | | |

家族 B 的灯效枚举也不同（§12.2）。另有若干家族在 A 基础上追加字段
（WinMacMode=54、TimeFormat=47、LogoDirection=27 等，见 `payload_semantics.md` §2.6）。

### 6.4 灯效参数的读取逻辑（网页 UI 的行为）

```
LedParameterType == 0：亮度/速度/混色 读每模式参数区[LedMode]
否则：亮度 = 字段6 + 1，速度 = 字段7
睡眠分钟 = 字段24 / 2
```

写入参数时先 `setLedParam` 改内存块，再整块 `SetProfile` 下发。

---

## 7. ledEffect（420 字节灯效参数）

420 = 20 个灯效模式 × 7 组 × RGB。**槽索引 = 灯效模式号（pt 值）**，不是键位：

```
mode 0:  byte[0..20]    = 7 组 × RGB（组0 = byte[0..2]，组1 = byte[3..5]，…）
mode 1:  byte[21..41]
…
mode 19: byte[399..419]
```

网页 UI 只写"主色组"（组 0，`mode*21 + 0..2`），其余 6 组留给固件/其他工具。
切换灯效模式时：SetLedEffect（写该模式主色）→ SetProfile（写 LedMode 字段）。
OFF（0）与 Music（19）不写颜色。

---

## 8. ledColors（378 字节单键颜色）

自定义灯效（SelfDefine）的逐键颜色。378 = 3 个平面 × 126 键：

```
R 平面: byte[0..125]
G 平面: byte[126..251]
B 平面: byte[252..377]
键 i 的颜色 = (byte[i], byte[126+i], byte[252+i])
```

**键索引 i = 列主序**：`i = row + 6*col`（row 0..5，col 0..20），
与键矩阵（§9）、`keyLayout` 平铺数组下标一致。

---

## 9. keyMatrix（504 字节键矩阵）

504 = 126 键 × 4 字节。索引同样为列主序 `i = row + 6*col`。

每键一个 u32 LE：

```
keyRaw = (keyMappingType << 24) | (keyMappingPara << 16) | (keyCode & 0xFFFF)
```

### 9.1 keyMappingType（`Rt` 枚举）

| 值 | 名称 | keyMappingPara | keyCode |
|---|---|---|---|
| 0 | KeyBoard | 修饰键掩码（bit0-7 = L-Ctrl/L-Shift/L-Alt/L-Win/R-Ctrl/R-Shift/R-Alt/R-Win） | HID 风格键码（0..255）；组合键 = `keyCode \| (掩码<<16)` 拆开存储 |
| 1 | Mouse | 动作 1..13：1左 2右 3中 4前进 5后退 6左滚 7右滚 8滚上 9滚下 10 X- 11 X+ 12 Y- 13 Y+ | 按键类=0x0100，轴类=0 |
| 2 | Media | 0 | Consumer Page usage（16 位，如 0xE2 静音） |
| 3 | Macro | 循环模式：1=循环 N 次，2=循环至按下，4=循环至松开 | `(次数<<8) \| 宏索引` |
| 4 | Custom | 0 | 1=Define1，2=Define2 |
| 5 | DPIKey | 1=+ 2=- 4=loop 10=lock | 0 |
| 6 | ProfileSwitch | 1=+ 2=- 4=loop | 0 |
| 7 | SpecialFun | 0 | 功能 id（§9.2） |
| 8 | LightSwitch | 子功能（§9.3） | 依子功能 |
| 9 | ReportRate | 1=+ 2=- 3=loop | **0=125Hz 1=250Hz 2=500Hz 3=1000Hz** |
| 10 | SnipeKey | 0 | 0 |
| 13 | FnKey | 0=Fn1 1=Fn2 | 0 |
| 15 | LodKey | — | — |
| 16 | Pc | 0 | 1=Power 2=Sleep 4=WakeUp |
| 18 | WebKey | — | — |

### 9.2 SpecialFun 功能 id（type 7 的 keyCode）

| id | 功能 | id | 功能 |
|---|---|---|---|
| 0x00 | WASD↔方向键互换 | 0x0C | 电量显示 |
| 0x01 | Win 键锁 | 0x0D | Win/Mac 切换 |
| 0x02 | 全键锁 | 0x0E | Windows 模式 |
| 0x03 | 宏录制 | 0x0F | Mac 模式 |
| 0x04 | 恢复出厂 | 0x10 | KB 模式 |
| 0x05..08 | BT 设备 1..4 | 0x22 | O_Mode |
| 0x09 | 2.4G（UI 上 BT4 显示为 USB） | 0x23 | L_Mode |
| 0x0A | EMI 测试 | 0x24 | Touch_Mode |
| 0x0B | 灯开关 | 0x25 | 6键模式 |

### 9.3 LightSwitch 子功能（type 8 的 para）

| para | 功能 | keyCode |
|---|---|---|
| 0 | 灯效模式 +/循环/loop | 0=loop，0x100=+，0x200=- |
| 1 | 灯效方向 | 同上 |
| 2 | 颜色模式（主/Logo/侧灯） | key 低位 0=主 1=Logo 2=侧灯 |
| 3 | 亮度 | 0=loop，0x100=+，0x200=- |
| 4 | 呼吸 | 同上 |
| 5/6/7/8 | 录制开始/保存/录制/重置 | — |
| **9** | **直接切到灯效模式** | `keyCode = 模式号 << 8` |
| 255 | KB_REC_Reset | — |

---

## 10. 宏（4096 字节宏区）

### 10.1 整体布局

```
偏移 0 .. 4N-1    目录：每条 4 字节 = { offset u16, length u16 }（N = 宏数）
偏移 4N ..        宏体依次存放
                  宏体 = byte0 名称长度(= 字符数×2，UTF-16LE 字节数)
                        + 名称 UTF-16LE
                        + 动作序列（每动作 4 字节）
```

读写单位：Dongle 按 8 块 × 512B（Get/SetMacros 带 block）；USB 按 512B 块
（GetMacros 逐块请求 / SetMacros `packageNum/packageIndex`）。

### 10.2 动作编码（4 字节）

```
byte0 = (action << 7) | (type << 4) | ((delay >> 16) & 0x0F)
byte1 = (delay >> 8) & 0xFF
byte2 = delay & 0xFF          delay 20 位，最大 0xFFFFF（1048575ms）
byte3 = key
```

- `action`：0=按下，1=抬起。**延时动作**线上表示为 `action 位=1, type=0, key=0`，
  其 20 位 delay 即延时毫秒数。
- `type`：0=普通键（key=键码，组合键可带修饰位）1=修饰键（key=224..231 短码）
  2=鼠标键（1左 2右 4中 8B4 16B5）3=光标X 4=光标Y 5=滚轮。

### 10.3 约束

- 名称最长 10 字符（=20 字节 UTF-16）。
- 宏区总长 4096 字节，BeiYing 家族驱动端无宏数量硬校验（写不下即超出）。
- 宏键绑定：键矩阵里 type=3（Macro），keyCode=`(重复次数<<8)|宏索引`，para=循环模式。
- 出厂默认宏（部分家族内嵌）：
  宏1 "Macro 1"：↑D↓D↑C↓C↑B↓B↑A↓A；宏2 "Macro 2"：↑C↓C↑B↓B↑A↓A（延时均 30ms）。

---

## 11. 键码体系

RK 私有键码空间（`D` 枚举，385 项）：

### 11.1 基础键（0..255，选录）

| 键码 | 键 | 键码 | 键 |
|---|---|---|---|
| 0 | 空 | 41 | ESC |
| 4..29 | A..Z | 42 | BackSpace |
| 30..39 | 1..0 | 43 | TAB |
| 40 | Enter | 44 | Space |
| 45..56 | - = [ ] \ ; ' ` , . / | 57 | Caps |
| 58..69 | F1..F12 | 70..72 | Print/ScrLock/Pause |
| 73..82 | Ins Home PgUp Del End PgDn → ← ↓ ↑ | 83..99 | 小键盘区 |
| 100 | \|（K45） | 101 | App |
| 104..106 | F13..F15 | 133..145 | K107/K56/K133/K14/K132/K131/K151/K150（矩阵特殊位） |
| 224..231 | L-Ctrl L-Shift L-Alt L-Win R-Ctrl R-Shift R-Alt R-Win（修饰短码） | | |

### 11.2 raw32 编码（≥65536，按 `raw>>24` 分类）

| type | 结构 | 含义 |
|---|---|---|
| 0 | `0x00MMKKKK` | 组合键。MM=修饰掩码（0x01 L-Ctrl … 0x80 R-Win），KK=基础键。如 Ctrl+A=65540，Alt+F4=262205，Win+D=524295 |
| 1 | `0x01PP0100` / `0x01PP0000` | 鼠标键。PP=1..13（见 §9.1） |
| 2 | `0x0200UUUU` | 多媒体。UUUU=Consumer usage：0xE2 静音、0xE9/EA 音量、0xCD 播放暂停、0xB5-0xB8 上/下一曲/停止/弹出、0x6F/70 屏幕亮度、0x192 计算器、0x194 我的电脑、0x221 搜索等 |
| 3 | `0x03000000\|idx` | 宏引用（KEY_MACRO0=50331648，KEY_MACRO1=50331649） |
| 4 | `0x04000001/2` | 自定义键 Define1/2 |
| 5 | `0x05PP0000` | DPI 键（PP=1 +/2 -/4 loop/10 lock） |
| 6 | `0x06PP0000` | Profile 切换（1 +/2 -/4 loop） |
| 7 | `0x07000000\|id` | 特殊功能（§9.2） |
| 8 | `0x08PPKK00` | 灯光控制（§9.3；切模式 = `0x08090000\|(mode<<8)`） |
| 9 | `0x09000000\|rate` | 回报率直切（0-3 = 125-1000Hz） |
| 13 | `0x0D000000/0x0D010000` | Fn1/Fn2 |
| 16 | `0x10000001/2/4` | Power/Sleep/WakeUp |

---

## 12. 灯效模式枚举与参数语义

### 12.1 家族 A（`pt` 枚举，主流）

| 值 | 名称 | 速度 | 亮度 | 备注 |
|---|---|---|---|---|
| 0 | OFF | ✗ | ✗ | |
| 1 | FixedOn（常亮） | ✗ | ✓ | 只有亮度/颜色 |
| 2 | Respire（呼吸） | ✓ | ✓ | |
| 3 | Rainbow（彩虹） | ✓ | ✓ | |
| 4 | FlashAway（闪灭） | ✓ | ✓ | |
| 5 | Raindrops（雨滴） | ✓ | ✓ | |
| 6 | RainbowWheel（彩虹轮） | ✓ | ✓ | |
| 7 | RippleShining（涟漪） | ✓ | ✓ | |
| 8 | StarsTwinkle（繁星） | ✓ | ✓ | |
| 9 | ShadowDisappear（阴影消散） | ✓ | ✓ | |
| 10 | RetroSnake（贪吃蛇） | ✓ | ✓ | |
| 11 | NeonStream（霓虹流） | ✓ | ✓ | 出厂默认模式 |
| 12 | Reaction（按键反应） | ✓ | ✓ | |
| 13 | SineWave（正弦波） | ✓ | ✓ | |
| 14 | SideScan（侧扫） | ✓ | ✓ | |
| 15 | RotatingWindmill（旋转风车） | ✓ | ✓ | |
| 16 | ColorfulWaterfall（七彩瀑布） | ✓ | ✓ | |
| 17 | Blossoming（百花绽放） | ✓ | ✓ | |
| 18 | SelfDefine（自定义） | ✗ | ✗ | 逐键颜色（§8） |
| 19 | Music（音乐律动） | — | — | 采样在固件侧，PC 端无麦克风逻辑 |

UI 范围：亮度 1..20（存储 0..19），速度 1..4（存储 0..4），睡眠 0..30 分钟（存储 ×2），
混色勾选（存储 color=7）。

### 12.2 家族 B（R87PRO RF 系）

```
0=OFF  9=RetroSnake  10=NeonStream  11=Reaction  12=SineWave  13=RotatingWindmill
14=ColorfulWaterfall  15=Blossoming  19=SelfDefine  20=Music
```

（无 ShadowDisappear / SideScan，其余编号前移。）

---

## 13. Dongle 密码 / 状态 / 主动上报

### 13.1 GetPassword（cmdId 5，dongle）/ 固件版本（cmdId 130，USB）

Dongle 响应（payload ≥10B）：

```
byte4..7  u32 LE ┐
byte8..9  u16 LE ┴→ pwd = getUint32(4) + getUint16(8)    数值相加
byte12/13        → version = 两字节各自 hex 拼接（如 01 02 → "0102"）
```

（两个家族版本号取 byte13/14，见 §15.2。）

USB 响应：payload 第 8、9 字节拼 hex 为固件版本，无密码。

触发时机：连接建立后 ActivelyReport 上报已连接 → 1 秒后 GetPassword；断开时密码清零。

### 13.2 GetDongleStatus（cmdId 7）

响应 `byte4 > 0` 表示键盘已通过 2.4G 连上接收器。

### 13.3 ActivelyReport（cmdId 10）

设备主动发 input report（reportId 19，19 字节）：

```
byte4 = 子类型（已知 2）
byte5 = 值（1=已连接，0=已断开）   仅子类型 2
```

子类型 2 时更新连接状态并触发密码读取。其余子类型忽略。

---

## 14. 恢复出厂

| 通道 | 命令 | 帧内容 |
|---|---|---|
| Dongle | SetFactory（6） | 19 字节帧，零载荷，`byte1=1` |
| USB | SetFactory（17） | 519 字节帧，`byte1=0, byte2=0, byte3=1, byte5=1`，payload 1 字节 0x01 |

网页驱动完整流程：重建默认键表（按 keyLayout）→ 下发恢复出厂 → 清空本地缓存 →
SetProfile(0) 写回默认 profile → 逐 (layer × table) SetKeyMatrix。
恢复出厂后设备端键表/灯效/宏全部回到固件默认值，**不可撤销**。

---

## 15. 家族变体表

### 15.1 33 个键盘家族总览

| fam | 代表型号 | USB reportId | Dongle | 额外命令 |
|---|---|---|---|---|
| 0 | R87PRO | 6（pid 459 用 9） | ✓ | — |
| 1 | R87PRO RF | 6（pid 459 用 9） | ✓ | —（profile 布局 B） |
| 2 | M87 系 | 9 | ✓ | TFT（12/13） |
| 3 | L75 系 | 6 | ✓ | WebKeyTab（18） |
| 4/5 | CB75-keyboard / CB68-keyboard | 6 | ✓ | WebKeyTab |
| 6/7 | M65 / M70 系 | 6 | ✓ | — |
| 8 | L98 | 9 | ✓ | — |
| 9 | N99 系 | 9 | ✓ | — |
| 10 | R98PRO 系 | 9 | ✓ | — |
| 11 | S98 系 | 9 | ✓ | TFT |
| 12 | F99 | 6 | ✓ | — |
| 13 | X87 系 | 9 | ✓ | WebKeyTab |
| 14 | K99 | 6 | ✓ | — |
| 15/16 | A70 / A72 | 9 | ✓ | WebKeyTab |
| 17 | R75 JP | 6 | ✗ | — |
| 18 | R65 系 | 6 | ✓ | — |
| 19 | S104 系 | 9 | ✓ | TFT |
| 20 | S85 系 | 9 | ✓ | TFT |
| 21 | M100 系 | 9 | ✓ | TFT |
| 22 | Ultra65 | 6 | ✗ | TFT |
| 23 | 84 系 | 6 | ✗ | TFT |
| 24 | 68 | 6 | ✓ | — |
| 25 | N80 系 | 9 | ✓ | TFT |
| 26/27 | As68 / S70 | 9（output/feature） | ✗ | 独立命令空间（§15.3） |
| 28 | M75 系 | 9 | ✓ | — |
| 29 | R98PRO V2 | 9 | ✓ | — |
| 30 | R108PRO | 9 | ✓ | — |
| 31 | R75PRO V2 | 6 | ✓ | WebKeyTab |
| 32 | MO1/MO3/K3/M3/M30/MG5 等 | 6 | ✗ | 键盘形态协议（设备为鼠标形态的键盘模式） |

全部 33 个家族的帧格式、cmdId、payload 布局**完全一致**（仅变量名不同），
差异只在：reportId（6/9）、profile 字段偏移（A/B）、附加命令（TFT/WebKeyTab）。

### 15.2 已知偏差清单

- 家族 B（fam1）：profile 布局 B、灯效枚举 B、GetPassword 版本号在 byte13/14。
- **19 字节帧 CRC 覆盖范围**：仅 iKe（fam0，RK-R87PRO dongle）覆盖 byte0..16；
  其余 26 个 dongle 家族覆盖 byte0..17。
- **LED 颜色 G/R 交换**（LED 效果每键写 G,R,B；单键颜色 G 平面在前）：
  EKe(CB75-keyboard)、HKe(RK-F99)、y3e(RK R65 2.4G)、U3e(RK R75PRO V2)
  及其 USB 伴侣类（kKe/jKe/kce/B3e）。
- **固件版本解析偏移**：Dongle GetPassword 多数读 byte12/13，pce（RK X87）读
  byte13/14；USB cmd130 多数读 payload 第 8/9 字节，sS(M87)/YKe(L98)/LB(M75)
  读第 6/7 字节。
- As68/S70（fam26/27）：独立命令空间 `gu`：SetKeyMatrix=1/Get=129、SetMacro=2/Get=130、
  SetConfig=3/Get=131、SetLedColors=9/Get=137、Factory=5；帧 byte0 为 interfaceId；
  宏块 192B × 4（总量 768B）；键矩阵命令无 layer（只有 table bit0）；
  灯色 375B（125×3）、灯效 60B（20×3）。
- 8 个 dongle 家族（CB68/M65/M70/L98/N99/F99/K99/N80）SetProfile 时把
  KbConnectMode（byte14）置 1 再下发。
- 鼠标（M3/M30/K3/MG5/MO1/MO3）另有独立的 `cmdPara` 协议（§16.1），
  与键盘协议不通用。

### 15.3 As68/S70 传输选择

优先 `sendReport(9, frame)`（HID 描述符含 outputReports[9] 时），否则
`sendFeatureReport(9, frame)`；读取优先 feature + inputreport，失败退化为
`getFeatureReport(9)` 轮询（间隔 8ms，超时 500ms，宏 800ms）。
固件版本探测依次试 feature 9 / feature 5 / getFeature(9)，正则 `^[0-9A-F]{4}$`
且排除 0000/0001/0101/1111/FFFF，读不到回退 "RK9007"。

---

## 16. 其余协议族

> 完整细节见 `notes/other_protocols.md`。此处仅记录通信结构，供扩展实现参考。

### 16.1 BeiYing 鼠标（cmdPara 版，519 字节，reportId 9）

```
byte0 = CRC（= sum(byte1..byte517) & 255）   注意 CRC 在帧首
byte1 = cmdId   byte2 = cmdPara
byte3 = packageNum   byte4 = packageIndex
byte5/6 = dataLength   byte7.. = payload
```

cmdId：1=SetKeyMapping、3=数据分包（宏）、4=写配置/恢复出厂、5/7=getOnline、
9=getBattery、68=读配置（400B）、72=固件版本、146=GetFwVer。响应 `byte3` 为长度。
另有 63 字节变体（RK-M3/K3/MG5，reportId 3）：`byte0=CRC, byte1=fixVal(101/80),
byte2=cmdRsp, byte3=len, byte4=sn, byte5=device/offset, byte6=rfSn, byte7=payloadLen`。

### 16.2 TLW（仅 CB75 鼠标，vid 0x320F，pid 0x22F2 有线 / 0x22F3 无线）

- reportId 4（协议，63 字节）+ reportId 5（固件升级）。
- 请求：`[0..1]=0, [2]=cmdId+0xA0, [3]=len, [4..5]=addr u16, [7..]=payload, [31]=2(无线)`
- 响应：byte2 回显命令（0xFF=拒绝）、byte3 回显长度、byte4-5 回显地址、byte6=ACK（0=成功）。
- 命令：读 BasicInfo=3/Functions=5/DefaultKeys=7/Keys=8/Battery=26；
  写 Begin=1/End=2/Functions=6/Keys=9/FactoryReset=13/Macros=21。
- 写流程：Begin → 分块写（56/24B）→ End → 回读逐字节比对。
- 固件升级：reportId 5，32 字节应答，16B/包，CRC-16/ARC（初值 0xFFFF、多项式 0xA001）。

### 16.3 QiWang

- 键盘（MG6 Pro 系）：`lL`，SDK worker 驱动；output reportId 由 HID 描述符动态解析。
- 鼠标 worker 版（MG6 Pro 等）：reportId 0，64 字节帧；命令 79 个（DPI/键表/宏/传感器/
  回报率/升级）。
- 鼠标直连 SDK 版（RK 5391K）：reportId 0，64 字节帧，`[0]=msg头(bit0-4=type, bit5=ack,
  bit6=bind, bit7=remoteId), [1]=main_cfg_type, [2]=sub_cfg_type, [3]=属性(bit0=方向,
  bit1=restore, bit2=store, bit3=modify, bit4=响应有效), [4..63]=payload`；
  **TEA 加密**（16 字节固定密钥 `CA BA A5 CA 6D 8A 2A BC BA 9E 5A CA CA 8B B8 9B`，
  delta 0x9E3779B9，32 轮，8B/块）。

### 16.4 SparkLink / JuPeng / HangSheng

与 BeiYing USB 同构的 worker 型驱动：主线程在 inputreport 里解析完整帧后
`worker.postMessage("report")` 通知 worker 发下一包；worker 回传数据时主线程
`setReport(reportId, data)` 写出。具体 reportId/命令空间见 `notes/other_protocols.md`。

### 16.5 RongYuan（A72-HE）

USB 走 feature report；蓝牙走 output report 且**首字节加 0x55 前缀**；
dongle 模式写前轮询 `getDeviceStatus`（最多 5 次、间隔 150ms）直到允许发送。

### 16.6 Gcome / Bytech / QMK

- Gcome（K99/R87ProV2/R99/T87/T98，vid 0x19F5）：设备匹配额外校验 productName，
  协议经 `T9l` 门面 + worker。
- Bytech：有独立附加路径（`attachBytechDevice`），协议经 `l_n` 门面。
- QMK：VIA 兼容协议（usagePage 0xFF00，usage 1），`I0` 门面。

---

## 17. WebHID 与 hidapi 的对应关系

复刻驱动（如 Python hidapi）时的映射：

| WebHID | hidapi（hidraw） |
|---|---|
| `requestDevice(filters)` | `hid.enumerate(vid, pid)` + `open_path` |
| `device.open()` | `open_path` 即打开 |
| `sendFeatureReport(id, data)` | `send_feature_report([id] + data)` |
| `receiveFeatureReport(id)` | `get_feature_report(id, 520)`；返回 buffer[0]=reportId，buffer[1:]=帧 |
| `sendReport(id, data)` | `write([id] + data)` |
| `inputreport` 事件 | 阻塞 `read(64, timeout_ms)`，数据含 reportId 首字节 |
| `device.close()` | `close()` |

Linux 下访问键盘 HID 接口通常需要 root 或 udev 规则（`KERNEL=="hidraw*", ATTRS{idVendor}=="258a", MODE="0666"`）。
hidapi 的 libusb 后端会自动 detach 内核驱动，hidraw 后端不会。

---

## 18. 实现注意点

1. **两套 cmdId**：USB（feature）与 Dongle（output）通道同一功能的 cmdId 数值不同，勿混用。
2. **board 恒为 0**：驱动所有读写都传 board=0。
3. **键索引列主序**：`i = row + 6*col`，与直觉的行主序相反，LED 颜色与键矩阵同用此约定。
4. **SleepTime = 分钟×2**；TapDelay 是 Tap 层配置不是延时；每模式灯效参数区偏移
   `56+2n`（家族 B 为 `83+2n`）。
5. **Dongle ACK**：byte1 bit7=1 表示要求重发；单包重试上限 10 次。
6. **USB 响应比请求多 1 字节头**：响应 payload 在 resp[9]（请求在 resp[8]，
   因为 resp[0] 是 reportId）。
7. **恢复出厂不可撤销**，且会重置键表/宏/灯效；网页驱动随后写回默认配置。
8. **宏区 4096 字节**：目录头 + 宏体，超过即溢出（驱动端不校验）。
9. **Music 模式无 PC 端采样**：设 LedMode=19 即可，律动由固件处理。
10. **节奏**：网页 worker 的精确节流参数未知（worker 源不在 bundle 内），
    建议保守参数：dongle 包间 ≥5ms、单包 ACK 超时 3s；USB 帧间 ≥10ms。
11. **R75PRO V2 的 Fn+Enter 电量 bug**：驱动内置的 WIN/FN1 布局表（`x_t`）在
    Enter 位（索引 81 = row 3 + 6×13）是 `NONE`，MAC/FN1 表（`b_t`）写的是
    `0x0700000C`——两者都不对。该固件真实电量键 = 特殊功能 **id 0x24**
    （u32 `0x07000024`，keyText 117440548 标注 "Battery"；枚举名 SP_Touch_Mode
    为历史遗留）。出厂与 EXE 驱动均写此值。网页驱动改 Win 方案任意键时整层
    写回，Enter 位被覆盖成 0。修复：把 WIN/FN1 索引 81 写为 `0x07000024`
    （rkctl：`keymap fix-fn-battery --matrix-be`）。
    另注意该型号键矩阵 u32 固件按**大端**解释（出厂数据字节反转存储），
    rkctl 用 `--matrix-be` 适配。再用网页驱动改 Win 方案键时该 bug 会复发。
