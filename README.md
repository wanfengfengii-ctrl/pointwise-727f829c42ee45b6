# 澄浜回用水站流量交班

澄浜回用水站使用一台清零式记录器。值班员累计设备收到的整数升数，采录员登记交班请求并保存清零前原读，班长决定未签班界是否成立。下一班可断开设备，按票领取已签班报和首执，并核对每段流量的来源。

## 运行

使用 Python 3.11 标准库，在项目根目录执行。

```text
python3 -B check_project.py
python3 -B -m ledger.application demo
python3 -B -m ledger.application demo --settlement sign
```

控制台物化项目时提供 `check_project.py`，它运行 `tests` 包的完整回归。独立使用项目源码时，可执行 `python3 -B -m unittest discover -s tests -t .`。演示在独立临时目录保存两个数据库，从 `examples/workday.json` 读取输入和手算预期。每条路线先比较实际签领及核账结果，再输出一条 `POINTWISE_SCENARIO`。不一致时以非零状态退出。

## 一天的交班

1. 值班员接入 `CH-01`。一致配置复用原设备、累计和业务历史，异参配置返回冲突。
2. 设备收到 3 L 和 4 L，累计 7 L。采录员登记 A 并保存清零前读点和原读。
3. 设备完成 A 对应的第一次清零，回包丢失。采录记为待查，设备继续计量。
4. 设备累积新的 11 L 并切出 B。B 的原段已查实，前票 A 仍待签时 B 不可签领。
5. 采录按原操作查回 A。班长可以撤 A，也可以先签 A。撤界仍保留实际清出的 7 L。
6. 班长签 B。撤 A 时 B 核销两段共 18 L，先签 A 时 A、B 分别核销 7 L 和 11 L。
7. 次班关闭设备后按票领取定稿与首执。撤界及未签分别返回对应状态。
8. 核账员根据定稿顺序复核本地原读、出处、核销和合计。零升与同值段都有独立原段身份。

## Python 接口

`ledger.application.open_station(root, offline=False)` 返回上下文管理器。在线打开会非破坏性初始化 `source.sqlite3` 和 `business.sqlite3`。`offline=True` 只打开已有业务库，支持签发已查实票、撤界、领取和核账。每个操作会按所需数据库提交。并行调用使用各自的 `open_station` 连接。

| 方法 | 输入与返回 |
| --- | --- |
| `configure(recorder, setting)` | 两个非空文本标识，返回固定 `DeviceConfig`。 |
| `record(recorder, liters)` | 接收非负 Python `int`，返回新 `CounterReading`。 |
| `reading(recorder)` | 返回当前累计、设备读点和已完成的清零序号。 |
| `cut(recorder, ticket, request)` | `ticket` 与固定 `request` 均为非空文本。返回 `CaptureResult`，含状态、稳定操作号及可用时的 `Segment`。演示可用 `lose_reply=True` 在设备提交后丢弃本次答复。 |
| `resume(recorder, ticket, request)` | 同参续办已登记票。先复用已查实结果或查回原设备终局，确知未执行且票有效时可续发。 |
| `withdraw(ticket)` | 撤销未签边界。重复办理返回原撤界状态，已签票返回 `already_signed`。 |
| `issue(recorder, ticket, request)` | 签发 `Issued`，包含 `OfficialReport` 和 `FirstReceipt`。同号同参复用已签结果。 |
| `receive(ticket)` | 读取原 `Issued`。未签返回 `not_issued`，撤界返回 `withdrawn`。 |
| `reconcile(ticket)` | 独立返回 `Reconciliation`，包含正式区间、有序出处和核账合计。 |
| `handover(ticket)` | 在同一读快照返回原 `Issued` 和复核结果。 |

业务拒绝通过 `StationError.code` 表示。`invalid_liters` 覆盖缺值、布尔值、负数和非整数。`unknown_recorder`、`configuration_conflict` 及 `request_conflict` 分别标识未登记设备、配置冲突和票号异参。来源未连接时，已确认的原段可直接重取，未知终局保持 `pending`。在线查回若确认旧票未执行且已撤界，返回 `withdrawn`。实际尚未清零的有效前票会以 `predecessor_uncut` 阻止新清零抢占物理顺序，已有清零终局的待查票继续允许后段采录。

签发时，本票未查实返回 `cut_pending`，前票未结清返回 `predecessor_pending`，已撤界但实际清零尚未查实造成的区间缺段返回 `missing_segment`。原读持久写失败返回 `evidence_write_failed`，设备累计与清零序维持原值。签存写失败返回 `issue_write_failed`，重开后可同号续签。核账不一致有 `audit_trace`、`audit_coverage`、`audit_total` 和 `audit_receipt` 分类。

## 持久化与核账口径

设备库保存计数、源读点和清零终局。采录在设备写事务固定读点，先独立提交业务库原读，其后才提交设备清零、实际序位和终局。终局证明对应操作及读点。采录凭据保留读值，查回匹配后才可用于核账。源读点随合法记录和实际清零推进。原段出处有记录器号、原操作号、清零前读点和实际清零序位。

业务票序用于裁决前票是否结清。物理清零序用于选取正式区间。报告覆盖上一正式末界之后至本界的连续原段，首报从序位 0 之后起算。每段最多核销一次，签定票态、逐段核销、定稿和首执同次提交。升数以十六进制文本落库，读入时解码为 Python 整数，累计与求和保持精确。领取读取存档，核账独立比较原读与定稿中的出处、覆盖、归属、首执及总量。

回归覆盖顺序切段、输入验证、一致初始化和重开、原读写失败、设备失答和暂不可查、前界待决、撤界承接与先签对照、签存回滚、超 64 位合计、零读与同值出处，以及停源旧件领取和核账不一致。
