# RK R75PRO V2：Web 驱动改键后 Win 布局 Fn+Enter 电量显示失效 —— 根因与修复报告

## 1. 现象

- 出厂状态：Win / Mac 两套映射方案下，Fn+Enter 均显示剩余电量。
- 用网页驱动修改 Win 方案任意按键（包括直接应用其默认配置）后，Win 布局下
  Fn+Enter 无反应；Mac 布局始终正常。
- 用 Windows EXE 驱动写默认配置则不会破坏该功能。

## 2. 该键盘的配置存储模型（底层）

### 2.1 键矩阵

键矩阵 = 2 套方案（table） × 4 层（layer） × 126 键 × 4 字节 = 每层 504 字节：

| 维度 | 取值 | 编码 |
|---|---|---|
| table | 0=WIN，1=MAC | 19 字节帧 byte2 bit7；USB 帧 byte1 bit2 |
| layer | 0=Nomal，1=FN1，2=FN2，3=Tap | 19 字节帧 byte3 bit4-5；USB 帧 byte1 bit0-1 |
| 键索引 | **列主序** `i = row + 6*col` | 物理 Enter = row3 col13 = **索引 81** |

每键 u32：`keyMappingType<<24 | keyMappingPara<<16 | keyCode`。
Fn+Enter 这类组合 = Fn 键按下后 FN1 层生效，Fn+Enter 的功能 = FN1 层 Enter 位
（索引 81）里存的那个键。

### 2.2 字节序（本型号的特殊性）

**R75PRO V2 固件把键矩阵的每个 u32 按大端解释**，出厂数据即以大端（字节反转）
存储。实证（出厂 dump，线字节 → 固件解读）：

| 槽位 | 线字节 | 大端解读 |
|---|---|---|
| ESC (41) | `00 00 00 29` | 0x29 = 41 ✓ |
| L_CTRL (0x10000) | `00 01 00 00` | 0x00010000 ✓ |
| Fn1 (0x0D000000) | `0D 00 00 00` | 0x0D000000 ✓ |
| Fn+Enter 电量键 | `07 00 00 24` | **0x07000024** ✓ |

网页驱动按小端 `setUint32` 读写，在该型号上写入的每个值固件看到的都是字节
反转形态（用户的 D 键位曾被写成 `0x07000000`=WASD 互换，即小端写 C=7 的
`07 00 00 00` 被大端读出）。

### 2.3 传输（2.4G Dongle 通道）

19 字节帧（output report 19 / input report 19）：

```
byte0=cmdId  byte1=包数(bit7=重传)  byte2=包序号(bit7=table)
byte3=低4位本包长度|(layer<<4)|(board<<6)  byte4..17=payload(≤14B)
byte18=CRC=(19+Σbyte0..16)&0xFF
```

- 读（GET）：发一包零载荷请求，设备连续回吐 input report，每包 14 字节，
  按序号拼接（36 包 = 504 字节）。GET 没有独立 ACK。
- 写（SET）：36 包逐包下发，每包等一个 ACK（byte1 bit7=0），bit7=1 重发。
- 命令：GetKeyMatrix=65 / SetKeyMatrix=1 / GetProfile=68 / SetProfile=4。
- 固件以 **SetProfile 作为键矩阵的提交触发**（网页驱动保存顺序即
  SetKeyMatrix → SetProfile）。

### 2.4 boardProfile 与问题无关

128 字节板载配置（灯效/回报率/睡眠等）。三份样本对比：

| 对比 | 差异 |
|---|---|
| EXE 驱动 vs 网页驱动 | **0 字节差异（完全一致）** |
| 出厂 vs 两驱动 | 仅 Debounce(4/3)、Logo2Mode(1/0)、每模式灯效亮度(4/19) |

EXE 与网页写出的 profile 一模一样，一个正常一个失效 → profile 不参与该功能。

## 3. 根因

两处叠加：

1. **网页驱动的布局表过时**。其内置 WIN/FN1 布局（`x_t`）Enter 位是 `NONE`，
   MAC/FN1 布局（`b_t`）Enter 位是 `0x0700000C`（SP_Power_Mode）——两个都错。
   该固件的真实电量键是特殊功能 **id 0x24**（键码 117440548，keyText 标注
   "Battery"；枚举名 SP_Touch_Mode 是历史遗留名）。EXE 驱动与出厂数据都写
   `0x07000024`。
2. **整层写回放大破坏**。网页驱动改 Win 方案任意键时把整层 504 字节按自己的
   布局表写回，Enter 位的电量键被覆盖成 0。又因该驱动按小端写而固件按大端
   读，写回的内容在固件侧普遍是字节反转形态。

三份键矩阵 dump（字节反转后）锁定根因：

| 状态 | WIN/FN1 Enter 位 | Fn+Enter |
|---|---|---|
| 出厂 | 0x07000024 | ✓ |
| EXE 驱动默认配置 | 0x07000024 | ✓ |
| 网页驱动默认配置 | 0x00000000 | ✗ |

## 4. 修复方法

1. 读 WIN/FN1 层（504 字节），逐 u32 字节反转还原。
2. 索引 81 写入 `0x07000024`（线字节 `07 00 00 24`，大端序）。
3. SetKeyMatrix 写回 WIN/FN1，逐包等 ACK。
4. 读回校验该位。

## 5. 排错历程要点

1. `0x0700000C`（SP_Power_Mode）无效：网页驱动布局表用的旧值，固件不认。
2. `0x07000030`（SP_BATT_IND_ENTER，兄弟型号用）无效。
3. `keymap diff` 暴露键矩阵字节反转（ESC 存 `00 00 00 29`）→ 发现大端存储。
4. 按大端重写 `0x0700000C` 仍无效。
5. 三份对照 dump（出厂/EXE/网页）逐槽 diff，锁定真值 **0x07000024**。

## 6. 注意事项

- 修复后用网页驱动再次修改 Win 方案任意键会**复发**（它仍会整层写回错误的
  布局表）。改键请用 rkctl（已适配大端），或改完再跑一次修复。
- 其他型号电量键 id 可能不同：主流型号见 `0x0C`（SP_Power_Mode）、
  R87PRO RF/X87/R108PRO 见 `0x30`（SP_BATT_IND_ENTER）。键矩阵大端存储目前
  仅在 R75PRO V2 确认。
- MAC 布局的 Fn+Enter 不受矩阵内容影响（该模式下固件为硬编码），故全程正常。
