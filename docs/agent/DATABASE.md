# ShoppingQnA 数据存储规则

- 最后更新时间：2026-07-23
- 对应提交：以当前 Git HEAD 为准
- 维护者：主 Agent，database 负责评审
- 状态：已生效

## 当前存储

- Chroma：保存文本向量和图片向量索引，本地目录为 chroma_data/。
  - Polyvore 文本向量 collection：`products_text_v3_v1`，text-embedding-v3 向量维度为 1024，业务标识为字符串 `item_id`。
  - 图片向量主 collection：`products_image_cnclip_v1`，Chinese-CLIP 向量维度为 512，业务标识为 Polyvore `item_id`。
  - `products_image_cnclip_v1` 与 `products_text_v3_v1` 当前均为 232 条，ID 集合完全一致。
  - 旧 `products_text` 未复用、未删除，旧代码入口保持不变。
  - 旧 `products_image` 已退出代码主链，但本轮不删除其本地数据。
- JSON：data/processed/ 保存处理后的商品数据，本地生成，不进入 Git；resolver 合并 `polyvore_neo4j_items_manifest.jsonl`、sample manifest 与 enriched JSONL，其中 enriched 优先；232 条基础中文检索记录保存在 `polyvore_neo4j_items_retrieval.jsonl`。
- MinIO：Neo4j 40 套切片对应的 232 个 Item 图片均保存为 `shopping-qna/polyvore/items/{item_id}.jpg`。
- 用户上传图片使用隔离前缀 `uploads/{session_id}/{image_id}.jpg`，由服务端生成对象键并校验会话归属；开发期 TTL 为 24 小时。
- 用户上传图片只允许临时保存和临时向量化，不写入 `products_text_v3_v1`、`products_image_cnclip_v1` 或 Polyvore 商品库。清理任务与生产鉴权尚未实现，必须在上线前补齐。
- M2-A/B 使用 `products_image_cnclip_v1` 执行只读 Top-3 相似查询；用户图片向量只存在于请求内存，当前存储数量和 schema 均未改变。
- M2-C 使用 Neo4j 只读查询跨输入图候选的共享 `Outfit`，未增加节点、关系、约束或索引，也未改变现有计数。
- M3-B 只读查询 `products_text_v3_v1` 召回替换候选，不写入任何 collection，也不查询 Neo4j。
- Neo4j：本机 `shopping-neo4j` 保存 Polyvore 最小图切片。
  - 节点：`Item(item_id)`、`Outfit(outfit_id)`。
  - 关系：`(:Item)-[:IN_OUTFIT]->(:Outfit)`。
  - 唯一约束：`Item.item_id`、`Outfit.outfit_id`。
  - 当前数据：232 个 Item、40 个 Outfit、233 条关系；重复执行相同导入不会增加计数。

## 未接入存储

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
- M3-C 仅使用 Neo4j 查询替换候选与保留单品的共享 `Outfit`；不创建或修改节点、关系、约束，不改变现有计数。
