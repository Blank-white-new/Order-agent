# 阶段 1 官方研究来源

访问日期统一为 `2026-07-15`。本文只记录官方资料和对产品设计的影响，不构成法律意见，也不代表项目已取得合规认证。网页可能持续更新；进入真实试点或欧洲阶段时必须重新核对版本并由专业人士审查。

| source_id | issuing_authority | title | publication_date | scope | relevance | design_implication | legal_review_required |
|---|---|---|---|---|---|---|---|
| SRC-001 | 香港个人资料私隐专员公署（PCPD） | [The Personal Data (Privacy) Ordinance — Ordinance at a Glance](https://www.pcpd.org.hk/english/data_privacy_law/ordinance_at_a_Glance/ordinance.html) | 持续更新（页面未列单一发布日期） | 香港个人资料保障原则概览 | 目的、最少收集、准确性、保留、安全、透明度及访问/更正 | 将目的限定、数据最小化、期限配置、访问控制和顾客权利流程列为设计闸门 | 是：实际业务、角色、告知和例外需香港法律意见 |
| SRC-002 | PCPD | [Artificial Intelligence: Model Personal Data Protection Framework](https://www.pcpd.org.hk/english/resources_centre/publications/files/ai_protection_framework.pdf) | 2024-06 | AI 采购、实施、使用及个人资料治理建议 | 风险评估、人工监督、数据治理、测试、监控和沟通 | 采用风险分级、人工接管、持续评测、供应商审查和审计追踪 | 是：框架应用与 PDPO 义务需结合真实部署确认 |
| SRC-003 | PCPD | [Guidance on Data Breach Handling and Data Breach Notifications](https://www.pcpd.org.hk/english/news_events/media_statements/press_20230630.html) | 2023-06-30 | 数据泄露准备、遏制、风险评估、通知考虑和记录 | 为电话、地址、转写、凭据泄露设计响应流程 | 后续建立事件预案、伤害风险评估、通知决策与证据留存 | 是：是否及何时通知须按事件事实确认 |
| SRC-004 | PCPD | [Guide to Data Protection by Design for ICT Systems](https://www.pcpd.org.hk/english/resources_centre/publications/guidance/guidance.html) | 2019-05 | ICT 系统的私隐设计 | 支持最少收集、默认保护和生命周期控制 | 在架构、默认配置、日志、删除和供应商接口中提前嵌入控制 | 是：具体控制充分性需专业评估 |
| SRC-005 | PCPD | [Report on Privacy Concerns on Electronic Food Ordering at Restaurants](https://www.pcpd.org.hk/english/resources_centre/publications/guidance/guidance.html) | 2024-01 | 餐厅电子点餐的私隐关注（中文报告） | 与订餐资料收集和透明度直接相关 | 真实试点前复核是否不必要强制收集资料、告知是否清晰 | 是：本项目电话场景与报告案例的适用差异需确认 |
| SRC-006 | 香港食物环境卫生署食物安全中心（CFS） | [Safe Kitchen — Food allergens](https://www.cfs.gov.hk/english/trade_zone/safe_kitchen/Food_allergens.html) | 最后修订 2023-05-25 | 餐饮场所过敏原、交叉污染和严重反应提示 | 要求从厨房核实，且交叉污染可能造成严重后果 | 严重过敏和交叉污染必须接管；系统不得自行保证安全 | 是：具体餐厅责任、话术和应急流程需食品安全/法律确认 |
| SRC-007 | CFS | [Beware of Allergens in Food](https://www.cfs.gov.hk/english/multimedia/multimedia_pub/multimedia_pub_fsf_231_04.html) | 2025-10-15 | 外出用餐隐藏配料、交叉污染与求助建议 | 支持对隐藏配料和制作流程保持保守 | 顾客应提示过敏，系统需把信息交权威厨房而非推断 | 是：不能把一般资料当作个案医疗建议 |
| SRC-008 | 香港政府数字政策办公室（DPO） | [Ethical Artificial Intelligence Framework v2.0](https://www.digitalpolicy.gov.hk/en/our_work/data_governance/policies_standards/ethical_ai_framework/doc/Ethical_AI_Framework_en.pdf) | 2025-12 | AI 指导原则、实践和影响评估 | 支持问责、透明、公平、安全、风险门控和人工复核 | 后续阶段使用影响评估与风险闸门记录高影响决策 | 是：框架为参考，不能替代适用法规分析 |
| SRC-009 | 香港政府 DPO | [Hong Kong Generative Artificial Intelligence Technical and Application Guideline v1.1](https://www.digitalpolicy.gov.hk/en/our_work/data_governance/policies_standards/ethical_ai_framework/doc/HK_Generative_AI_Technical_and_Application_Guideline_en.pdf) | 2025-12 | 生成式 AI 技术风险、治理原则和使用指引 | 涉及数据泄露、错误、偏差、责任和安全 | 保留规则优先、结果验证、离线评测、供应商和错误降级要求 | 是：未来是否使用生成式 AI 及其责任需独立审查 |
| SRC-010 | 欧盟（EUR-Lex） | [Regulation (EU) 2016/679 (GDPR)](https://eur-lex.europa.eu/eli/reg/2016/679/oj) | 2016-04-27 | 欧盟个人资料保护法律框架 | 未来欧洲阶段的数据角色、原则、权利和安全基线 | 欧洲阶段按目标国家和处理活动重新设计，不从香港模拟推导合规 | 是：必须由欧盟/当地法律专业人士确认 |
| SRC-011 | 欧盟（EUR-Lex） | [Regulation (EU) 2024/1689 (Artificial Intelligence Act)](https://eur-lex.europa.eu/eli/reg/2024/1689/oj) | 2024-06-13；Official Journal 2024-07-12 | 欧盟统一 AI 规则与风险义务 | 未来部署需判断角色、用途和风险分类 | 在欧洲范围确定后进行 AI Act 适用性、透明度和供应链审查 | 是：不能在阶段 1 预判产品最终分类或义务 |
| SRC-012 | 欧盟委员会 | [What data can we process and under which conditions?](https://commission.europa.eu/law/law-topic/data-protection/rules-business-and-organisations/principles-gdpr/overview-principles/what-data-can-we-process-and-under-which-conditions_en) | 持续更新（页面未列单一发布日期） | GDPR 目的限定、最小化、准确、保留和安全原则说明 | 便于将原则转换为工程需求 | 设计保留配置、删除复核、最小字段和技术/组织控制 | 是：概览不能替代法律文本和本地实施审查 |
| SRC-013 | European Data Protection Board（EDPB） | [Automated decision-making and profiling](https://www.edpb.europa.eu/documents/guideline/automated-decision-making-and-profiling_en) | 2018-05-25（EDPB endorsement） | 自动化决定和画像指南入口 | 支持未来评估自动化对个人的影响和人工介入 | 保留人工请求权、解释和风险评估；不默认建立长期顾客画像 | 是：订餐决定是否落入相关条款取决于实际影响和用途 |

## 使用限制

- 官方资料中的建议不自动等于本项目已满足法律义务。
- 食品安全资料只支持风险控制设计，不构成医疗建议或餐厅个案保证。
- `publication_date` 为文件版本/发布信息；“持续更新”页面应在每个发布闸门重新访问。
- 香港模拟结果不得作为欧洲合规证据；欧洲目标国家、服务模式和数据流确定后需重新研究。
