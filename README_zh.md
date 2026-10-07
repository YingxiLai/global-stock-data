# Global Stock Data 投资研究助手

这是 [上游项目](https://github.com/simonlin1212/global-stock-data) 的公开正式 fork，基于提交 `5f27525709ab043b91e53d7a420ce6d46e66a0ce` 重建为 v3.0.0 Python 包、CLI 和可选本地 stdio MCP。

默认离线，示例全为合成数据。SEC、Treasury、CFTC 仅在显式启用、满足各自访问条件后读取。Cboe、Yahoo、FINRA 与未核实前端来源默认禁止在线采集，没有宽泛的“全部合规”开关。没有实时行情供应商、券商、下单、转账或后台提醒。

运行、精确验证命令和在线边界见 [README](README.md)。核心运行时零第三方依赖；质量工具和可选官方 MCP SDK 都锁定版本与哈希。

研究流程保留原问题、已经回答的范围、仍未解决部分。数据状态与回答准备度分开；窄查询不要求个人问卷，宽泛决策最多追问两个必要问题。事实和计算必须带证据，推断/情景明确假设。观察列表不等于持仓或监控，用户决定不等于成交，交易仍由人执行。

- [产品与交互规格](PRODUCT_SPEC.md)
- [逐项修复及延期矩阵](docs/review-matrix.md)
- [上游功能迁移清单](docs/migration.md)
- [来源政策和限制](docs/source-policies.md)
- [验收与验证范围](docs/acceptance.md)

XBRL 保留单位、期间、申报编号和修订。当前不支持 IFRS/20-F/40-F 规范化，也不提供完整历史时点证券池或回测。期权 vol/OI 只作活动筛选，真实净 delta 必须有带符号持仓和真实乘数。FINRA 局部场外设施数据不等于全市场或空头余额。政府公开数据也须遵守具体访问政策。

原 Apache-2.0 LICENSE 保留，修改说明见 [NOTICE](NOTICE)。本 fork 没有继承上游“全面实测可用”的宣称，未运行的在线端点明确列为未验证。
