# 匿名共享学习规范

本模式把不同安装端发现的结构性问题汇总为候选证据。它不是聊天遥测、用户画像或远程自我改写系统。

## 授权模型

- 默认关闭；安装者必须主动执行一次`enable`并接受匿名同步说明。
- 启用后，白名单事件可自动提交，不再逐条确认。
- `disable`立即停止后续提交；不开启隐式重启或静默重新授权。
- 一次启用不授权上传新的字段类型。字段或用途变化必须升级版本并重新取得一次授权。
- 产品或运行环境要求确认外部写操作时，以产品确认机制为准，本Skill不得绕过。

首次授权必须先显示完整中文提示，不得折叠为笼统的“同意遥测”：

```text
匿名共享学习说明

不会收集或上传：聊天内容、提示词、助手回复、小说/脚本/图片等作品内容、附件或文件内容、文件路径、网址、姓名、账号、密码、手机号、邮箱、密钥、Cookie、设备标识、持久用户标识。

只会上传：Skill名称和版本、预先定义的问题分类、流程阶段、公开规则编号、修复状态、严重程度及聚合次数。所有字段均为固定枚举或受限代码，不允许自由文本。

提交后只做匿名聚合，用于发现Skill的共性问题；不会根据这些数据直接修改Skill。你可以随时关闭匿名共享学习。
```

提示后由安装者主动选择接受或取消。命令行自动安装可以通过明确的`--accept-anonymous-sync`参数表达这一次授权，但不得默认补上该参数。

## 数据最小化

客户端只接受以下字段，不允许附加字段：

| 字段 | 约束 | 用途 |
|---|---|---|
| `schema_version` | 固定为`1` | 兼容校验 |
| `skill_name` | 小写字母、数字、连字符，1至64字符 | 定位Skill |
| `skill_version` | `X.Y.Z` | 定位版本 |
| `event_type` | 固定枚举 | 区分违规、失败、回归或修复验证 |
| `stage_code` | 固定枚举 | 定位流程阶段 |
| `issue_code` | 固定枚举 | 聚合问题类型 |
| `rule_id` | 仅大写字母、数字、下划线和连字符，最多24字符 | 定位公开规则；不得由项目名、人名或作品内容生成 |
| `result` | 固定枚举 | 标识未解、局部修复或验证通过 |
| `severity` | `low`、`medium`或`high` | 排序候选问题 |
| `client_version` | `X.Y.Z` | 协议兼容 |
| `occurrence_count` | 1至100整数 | 本次聚合数量 |

固定枚举由客户端脚本定义。任何用户输入、助手输出、自由文本、作品内容、提示词、附件、路径、URL、时间戳、IP地址、账号、密码、密钥、Cookie、设备ID或持久安装ID都不得进入载荷。

客户端在网络请求前进行严格结构校验。不能映射为枚举的问题留在本地M1记录，不提交，也不为了提交而把原文改写进`rule_id`。

## 服务端存储

接收端必须：

1. 限制请求体大小并再次执行相同的严格白名单校验；
2. 按完整白名单字段计算不可逆指纹，只保存字段组合和累计次数；
3. 相同指纹使用原子增量，不保存逐条请求正文；
4. 学习数据库不保存来源IP、请求头、Cookie、User-Agent或精确提交时间；
5. 关闭应用层访问日志；部署平台或反向代理也应关闭或最小化访问日志；
6. 不提供公开的报告明细查询，不把聚合数据返回给匿名提交者；
7. 将版本发布信息作为独立只读数据，不通过提交接口改变发布版本。

本Skill保留Python本地服务器用于受控测试，同时附带`scripts/cloudflare-worker`免费云端接收端。公网部署必须使用HTTPS、关闭Worker调用日志，并确认账号停留在Free计划。免费额度耗尽时允许请求失败，不自动升级付费方案。

### Cloudflare免费部署

免费云端接收端使用Workers与D1，只保存与本节相同的聚合字段。部署前完整运行项目测试；部署操作需要所有者登录自己的Cloudflare账号，不索取或保存账号密码、API令牌或浏览器Cookie。

部署顺序：

1. 在`scripts/cloudflare-worker`运行`npm test`；
2. 由所有者在Wrangler授权页自行登录；
3. 创建名为`caoyu-anonymous-learning`的D1数据库，位置提示使用`apac`；
4. 把Wrangler返回的数据库ID写入`wrangler.jsonc`的`database_id`；
5. 对远端数据库应用`migrations/0001_init.sql`；
6. 部署Worker并取得`workers.dev` HTTPS地址；
7. 验证`/health`、合法报告、非法隐私字段拒绝和D1聚合；
8. 只有全部验证通过后，才把该HTTPS地址设为分享包的默认同步端点。

`wrangler.jsonc`必须保持`observability.enabled: false`和`observability.logs.invocation_logs: false`。Worker代码不得读取`request.cf`、`CF-Connecting-IP`、Cookie、User-Agent或其他来源标识。Cloudflare作为网络服务商仍会为提供服务而处理必要网络数据；这里保证的是本应用不读取、记录或保存这些信息。

## 客户端命令

以下示例中的配置文件只保存在本机，不会上传：

```powershell
python scripts/anonymous_learning_client.py --config <本机配置路径> enable --accept-anonymous-sync
python scripts/anonymous_learning_client.py --config <本机配置路径> status
python scripts/anonymous_learning_client.py --config <本机配置路径> submit --skill-name caoyu-ai-director --skill-version 1.0.0 --event-type rule_violation --stage-code video_prompt --issue-code unexpected_field --rule-id R17 --result fixed_locally --severity medium --client-version 1.3.0
python scripts/anonymous_learning_client.py --config <本机配置路径> disable
```

默认接收端为`https://caoyu-anonymous-learning.caoyu6059777.workers.dev`。如所有者迁移服务，可在首次启用时通过`--endpoint <新的HTTPS地址>`覆盖；无论是否使用默认值，都必须显式加入`--accept-anonymous-sync`完成一次授权。

实际调用时不得把用户内容拼入命令参数。自动模式只从内部诊断结果选择枚举值。

## 所有者学习流程

1. 只读导出聚合计数；不按用户或设备切分。
2. 按影响、复现性和版本范围选择候选，不以出现次数替代真实性检查。
3. 使用合成输入重新构造测试，不恢复或猜测任何原始用户内容。
4. 按M2至M8执行根因定位、补丁、备份、测试和发布。
5. 发布新版后，客户端可读取公开的最新版本信息；更新Skill仍遵循安装与修改授权。

## 失败与停用

- 网络错误、服务端拒绝或字段不兼容时，客户端清晰报错并停止，不降级发送更多信息。
- 不建立离线原文队列。若需要重试，只能重新生成同一份白名单事件。
- 发现服务端误存逐条记录或访问日志包含来源信息时，暂停同步，先修复并按部署方的数据治理流程清理。
