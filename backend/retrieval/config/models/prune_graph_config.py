# Copyright (c) 2024 Microsoft Corporation.
# Licensed under the MIT License

"""Parameterization settings for the default configuration."""

from pydantic import BaseModel, Field

from retrieval.config.defaults import retrieval_config_defaults


class PruneGraphConfig(BaseModel):
    """Configuration section for pruning graphs."""

    min_node_freq: int = Field(
        description="The minimum node frequency to allow.",
        default=retrieval_config_defaults.prune_graph.min_node_freq,
    )
    max_node_freq_std: float | None = Field(
        description="The maximum standard deviation of node frequency to allow.",
        default=retrieval_config_defaults.prune_graph.max_node_freq_std,
    )
    min_node_degree: int = Field(
        description="The minimum node degree to allow.",
        default=retrieval_config_defaults.prune_graph.min_node_degree,
    )
    max_node_degree_std: float | None = Field(
        description="The maximum standard deviation of node degree to allow.",
        default=retrieval_config_defaults.prune_graph.max_node_degree_std,
    )
    min_edge_weight_pct: float = Field(
        description="The minimum edge weight percentile to allow. Use e.g, `40` for 40%.",
        default=retrieval_config_defaults.prune_graph.min_edge_weight_pct,
    )
    remove_ego_nodes: bool = Field(
        description="Remove ego nodes.",
        default=retrieval_config_defaults.prune_graph.remove_ego_nodes,
    )
    lcc_only: bool = Field(
        description="Only use largest connected component.",
        default=retrieval_config_defaults.prune_graph.lcc_only,
    )
