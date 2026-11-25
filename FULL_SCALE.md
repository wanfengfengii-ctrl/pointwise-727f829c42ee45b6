# 满量程自保采录

量程为 10 L 的记录器在站库停写时仍会收到脉冲。第十个脉冲触发第一次实清，原段为 10 L。若站库恢复后空表办理 A，A 承接原段。若 A 绑定前已进 4 L，则必须再实清一次，A 的报告保留两条原段，合计 14 L。

## 现场调用

- 沿用 `ledger.application.open_station` 和 `station.configure(recorder, setting)`。新增 `station.enable_full_scale(recorder, capacity)`，在已登记设备首次记录或实清前启用。量程是正整数升，布尔值无效。同量程重复启用沿用原配置，改量程或在已有普通采录后启用须拒绝。此模式一直沿用至重开后。
- 新增 `source.counter.pulse(db, recorder)`。值班员可独立使用 `source.store.open_source` 打开 `source.sqlite3`，只传该设备连接，返回提交后的 `CounterReading`。每次有效调用接纳 1 L。触及量程时，脉冲、带出处的原段及实清在同一次设备提交生效，失败时均不生效。设备库重开后原段仍能接回。未启用时拒绝 `pulse`。启用后原 `record` 拒绝，继续使用原 `reading` 查看实际状态。
- 原 `cut(recorder, ticket, request, *, lose_reply=False)` 与 `resume(recorder, ticket, request)` 仍使用相同的输入和 `CaptureResult`。设备确认绑定时，累计有值就实清余量。累计为零时，最近一次物理清零必须是未归票的自保原段，才可直接承接。承接不产生新清零。没有可承接原段时，`CaptureResult.status` 为 `no_new_boundary`，`segment` 为空，本次不登记有效票或占票序。此后可用 `cut` 再办，单独调用 `resume` 仍返回 `unknown_ticket`。
- 成功绑定固定票号、记录器、请求以及实际末界。同号同参可重取，异参返回 `request_conflict`。设备确认时以实际状态为准，即使站端此前看见空表。`lose_reply=True` 模拟源端首次成功提交后、站端收到终局前丢答，首次返回 `pending` 且无原段。设备已有终局的票，即使站库还未实收，也可重开后按原参 `resume`。已实收的终局返回 `confirmed`，其 `operation` 是人工票操作号，`segment` 是实际末段。读点沿用原口径，每个已接纳脉冲和每次物理清零各推进一次，承接本身不推进。人工实清操作仍使用 `cut/` 前缀，自保原操作须稳定并使用不同的命名空间。
- 同一物理末界只归一票。较早票已有设备归属终局时，允许后票先完成采录。签发沿成功归票顺序，前票未签或目标区间尚未实收齐备均不得签发。自保模式的票不办理撤界，停源也不得撤界。普通模式的撤界、签领、既有数据和回归照常。

## 交班与核账

继续使用 `issue`、`receive`、`reconcile`、`handover`。正式区间从上一已签末界之后到本票实际归属的末界，按物理清零序交付全部原段。签存失败不得留新报告、核销或首执，已接回的原据可继续用于签发。站库应能单独签发已齐备的票。报告中保留票名、有序原值、实际操作号、清零前读点、实际清零序及升数合计，`through` 和末条原段给出本票的归属结果。停源重开按原号领同一首执，核账须用本地原段和持久归属复核该结果。

`examples/full_scale.json` 是联动样例。四个追加脉冲先到时，A 签第 1、2 段，原读点为 10、15，原值为 10、4 L。若 A 先承接自保段而答复丢失，随后四个脉冲再到，A、B 分别签第 1、2 段，各自领到 10 L、4 L。在第二条路线中，B 在追加脉冲前办理会返回 `no_new_boundary`，进水后再办可正常登记。两条路线先在站库持有写锁时从独立设备连接送满量程，再重开设备确认。夹具在第一条路线还会拒绝一次首执写入，检查离线续签结果。

项目现有 `.pointwise-runtime.json` 提供运行入口，维持 `version` 为 1、`kind` 为 `cli`。`setup` 记录前置命令列表，`verify` 和 `demo` 各记录一个命令的参数数组。交付时把联动核验和离线签领演示接进该清单。`python3 -B full_scale_fixture.py verify` 先运行完整原回归，再检查自保路线，断言出错时退出非零。`python3 -B full_scale_fixture.py demo` 输出按前置进水路线实际签领的原段和首执。两条命令在功能接通后使用。基线可用 `python3 -B full_scale_fixture.py probe-v1` 查看普通模式在同一输入下的单段结果。
