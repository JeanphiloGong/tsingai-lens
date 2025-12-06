import logging

from graphrag.builder import GraphBuilder
from graphrag.community import CommunityManager

logger = logging.getLogger(__name__)


class GraphService:
    def __init__(self, graph_builder: GraphBuilder, community_manager: CommunityManager):
        self.graph_builder = graph_builder
        self.community_manager = community_manager
        logger.info("初始化 GraphService")

    def ingest_chunks(self, chunks, doc_id: str, source: str) -> None:
        logger.info("开始构图，doc_id=%s，source=%s，chunk_count=%s", doc_id, source, len(chunks))
        self.graph_builder.ingest_chunks(chunks, doc_id=doc_id, source=source)
        self.community_manager.rebuild()
        logger.info("构图完成并重建社区，doc_id=%s", doc_id)

    def snapshot(self):
        nodes = self.community_manager.store.list_nodes()
        edges = self.community_manager.store.list_edges()
        logger.info("获取图快照，节点数=%s，边数=%s", len(nodes), len(edges))
        return {
            "nodes": nodes,
            "edges": edges,
        }
