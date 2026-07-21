# ShoppingQnA 数据存储规则

- 最后更新时间：2026-07-20
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent，database 负责评审
- 状态：已生效

## 当前存储

- Chroma：保存文本向量和图片向量索引，本地目录为 chroma_data/。
  - Polyvore 文本向量 collection：`products_text_v3_v1`，text-embedding-v3 向量维度为 1024，业务标识为字符串 `item_id`。
  - 图片向量主 collection：`products_image_cnclip_v1`，Chinese-CLIP 向量维度为 512，业务标识为 Polyvore `item_id`。
  - 两个 Polyvore collection 当前均为同一组 5 条小样本，ID 集合完全一致。
  - 旧 `products_text` 未复用、未删除，旧代码入口保持不变。
  - 旧 `products_image` 已退出代码主链，但本轮不删除其本地数据。
- JSON：data/processed/ 保存处理后的商品数据，本地生成，不进入 Git；推荐 smoke 只读合并 `polyvore_items_sample.jsonl` 与 `polyvore_items_enriched_sample.jsonl` 解析展示 metadata，不写回文件。

## 未接入存储

- Neo4j 尚未接入，不是当前存储；src/graph/ 除抽象、返回空列表的 Dummy 实现和二期 TODO 占位外，仅有从 Polyvore `valid.json` 临时派生的进程内共现索引，该索引不落盘、不属于持久化存储。
- 关系型数据库：当前尚未引入，因此不存在已批准的业务表结构。

## 设计原则

- 先确认真实查询、写入、一致性和数据量需求，再设计结构。
- 当前查询不需要时不提前拆表、分库或分表。
- 索引必须对应真实查询条件。
- 业务代码不得绕过迁移直接改变结构。

## 变更门禁

建表、删表、修改字段类型、主键、外键、唯一约束、图关系约束或生产索引前，必须：

1. 由 database 给出最小方案；
2. 说明兼容性和数据风险；
3. 给出向前迁移和回滚步骤；
4. 获得用户批准；
5. 在测试环境验证后再考虑生产执行。
