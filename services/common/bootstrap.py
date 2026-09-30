import asyncio

from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError

from services.common.migrate import migrate
from services.common.provision_api import provision_local_api
from services.common.settings import InfrastructureSettings


async def main():
    settings = InfrastructureSettings()
    if settings.environment == "production":
        raise RuntimeError(
            "Provision production topics and database roles through deployment tooling"
        )
    await migrate()
    await provision_local_api()
    client = AIOKafkaAdminClient(**settings.kafka_options())
    await client.start()
    try:
        for name in (
            settings.raw_topic,
            settings.clean_topic,
            settings.quality_topic,
            settings.quarantine_topic,
        ):
            try:
                await client.create_topics(
                    [
                        NewTopic(
                            name,
                            num_partitions=6,
                            replication_factor=1,
                            topic_configs={
                                "retention.ms": "604800000",
                                "retention.bytes": "1073741824",
                            },
                        )
                    ]
                )
            except TopicAlreadyExistsError:
                pass
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
