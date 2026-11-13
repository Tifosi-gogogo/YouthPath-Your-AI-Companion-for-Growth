# DeepSeek Flash 真实联调记录

日期：2026-11-13；软件：0.7.0。

## 配置与凭据

- 根地址：`https://api.deepseek.com`；模型：`deepseek-flash`。
- 官方参数来源：https://api-docs.deepseek.com/ 。通过现有 OpenAI 兼容 Chat Completions 链路调用，没有修改生产代码或重新打包。
- 地址和模型已通过 SettingsStore 保存到本机；密钥只经子进程环境传递，在当前软件内存使用，未写入源码、配置、验收文档或报告，也未设置永久环境变量。关闭软件后需重新填写密钥。
- 本轮使用源码版打开真实 MainWindow，保持在线模式；不影响已有历史，测试创建独立新会话。

## 真实服务结果

连接测试使用项目 tools.check_api，经 LLMClient 调用正式服务：HTTP 200，耗时 2860 ms，返回正文 15 字符。

主聊天实际经过 MainWindow → ChatController → ChatWorker → LLMClient → parse_response → HistoryStore。使用无个人隐私的虚构问题，依次测试论文与社团时间冲突、承接每天两小时的安排、向负责人解释时间限制。

| 轮次 | 耗时 | 结果 | 系统规则及对话消息数 | 解析 |
| --- | --- | --- | --- | --- |
| 1 | 4078 ms | 成功 | 2 | JSON 合法，含标签及建议 |
| 2 | 5860 ms | 成功 | 4 | 普通文本降级，标签及建议为空 |
| 3 | 3766 ms | 成功 | 6 | 普通文本降级，标签及建议为空 |

三轮后从 HistoryStore.latest() 重新读取，确认会话 ID 和六条消息数量一致。可用正文未因格式降级丢失，软件留在在线聊天供继续使用。

## 验收边界

本次确认真实服务调用、连续对话、解析降级和本机持久化正常；未声称结构化字段稳定输出。回复质量仍需人工复核：例如第二轮时间安排未填满两小时，第三轮将总空余时间误说成社团可用时间。没有据此更改提示词或宣称专业安全验收通过。

服务商控制台调用明细未独立核对；真实性证据为正式 HTTPS 请求 HTTP 200、实际模型正文、后台请求标识及软件成功事件。已有旧版 software_release_verification.json 属历史打包记录，本次未重写其构建结论。

脱敏验收报告：当前聊天 outputs 下的 DeepSeek_Flash连接验证.json 和 DeepSeek_Flash三轮验收.json。报告包含虚构测试问题与模型回复，不含密钥。
