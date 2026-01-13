# Copyright (c) 2025 Microsoft Corporation.
# Licensed under the MIT License

"""LiteLLM Retry Factory."""

from retrieval.config.defaults import DEFAULT_RETRY_SERVICES
from retrieval.factory.factory import Factory
from retrieval.language_model.providers.litellm.services.retry.retry import Retry


class RetryFactory(Factory[Retry]):
    """Singleton factory for creating retry services."""


retry_factory = RetryFactory()

for service_name, service_cls in DEFAULT_RETRY_SERVICES.items():
    retry_factory.register(strategy=service_name, service_initializer=service_cls)
