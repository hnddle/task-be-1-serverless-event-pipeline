/**
 * Cosmos DB 클라이언트 싱글턴 및 컨테이너 초기화.
 *
 * @azure/cosmos SDK를 사용하여 Cosmos DB에 접근한다.
 * 5개 컨테이너: events, dead-letter-queue, circuit-breaker, rate-limiter, leases.
 *
 * SPEC.md §3.5 참조.
 */

import { Container, CosmosClient, Database, PartitionKeyDefinition } from '@azure/cosmos';
import type { Settings } from '../shared/config';
import { getLogger } from '../shared/logger';

const logger = getLogger('cosmos-client');

interface ContainerDefinition {
  id: string;
  partitionKey: string;
  ttl: number | null;
  indexingPolicy: Record<string, unknown> | null;
}

export const CONTAINER_DEFINITIONS: ContainerDefinition[] = [
  {
    id: 'events',
    partitionKey: '/clinic_id',
    ttl: null,
    indexingPolicy: {
      automatic: true,
      indexingMode: 'consistent',
      includedPaths: [{ path: '/*' }],
      excludedPaths: [{ path: '/"_etag"/?' }],
      compositeIndexes: [
        [
          { path: '/status', order: 'ascending' },
          { path: '/event_type', order: 'ascending' },
          { path: '/created_at', order: 'descending' },
        ],
      ],
    },
  },
  {
    id: 'dead-letter-queue',
    partitionKey: '/clinic_id',
    ttl: null,
    indexingPolicy: null,
  },
  {
    id: 'circuit-breaker',
    partitionKey: '/id',
    ttl: null,
    indexingPolicy: null,
  },
  {
    id: 'rate-limiter',
    partitionKey: '/id',
    ttl: 60,
    indexingPolicy: null,
  },
  {
    id: 'leases',
    partitionKey: '/id',
    ttl: null,
    indexingPolicy: null,
  },
  {
    id: 'logs',
    partitionKey: '/correlation_id',
    ttl: 604800, // 7일 자동 만료
    indexingPolicy: {
      automatic: true,
      indexingMode: 'consistent',
      includedPaths: [{ path: '/*' }],
      excludedPaths: [{ path: '/"_etag"/?' }],
      compositeIndexes: [
        [
          { path: '/correlation_id', order: 'ascending' },
          { path: '/timestamp', order: 'descending' },
        ],
      ],
    },
  },
];

let _client: CosmosClient | null = null;
let _database: Database | null = null;

export function getCosmosClient(settings: Settings): CosmosClient {
  if (!_client) {
    _client = new CosmosClient({
      endpoint: settings.COSMOS_DB_ENDPOINT,
      key: settings.COSMOS_DB_KEY,
    });
    logger.info(`Cosmos DB 클라이언트 생성 완료: ${settings.COSMOS_DB_ENDPOINT}`);
  }
  return _client;
}

export function getDatabase(settings: Settings): Database {
  if (!_database) {
    const client = getCosmosClient(settings);
    _database = client.database(settings.COSMOS_DB_DATABASE);
    logger.info(`Cosmos DB 데이터베이스 참조: ${settings.COSMOS_DB_DATABASE}`);
  }
  return _database;
}

const VALID_CONTAINER_NAMES = new Set(CONTAINER_DEFINITIONS.map((d) => d.id));

export function getContainer(settings: Settings, containerName: string): Container {
  if (!VALID_CONTAINER_NAMES.has(containerName)) {
    throw new Error(
      `알 수 없는 컨테이너: ${containerName}. 유효한 이름: ${[...VALID_CONTAINER_NAMES].sort().join(', ')}`,
    );
  }
  const database = getDatabase(settings);
  return database.container(containerName);
}

export function getEventsContainer(settings: Settings): Container {
  return getContainer(settings, 'events');
}

export function getDlqContainer(settings: Settings): Container {
  return getContainer(settings, 'dead-letter-queue');
}

export function getCircuitBreakerContainer(settings: Settings): Container {
  return getContainer(settings, 'circuit-breaker');
}

export function getRateLimiterContainer(settings: Settings): Container {
  return getContainer(settings, 'rate-limiter');
}

export function getLeasesContainer(settings: Settings): Container {
  return getContainer(settings, 'leases');
}

export function getLogsContainer(settings: Settings): Container {
  return getContainer(settings, 'logs');
}

export async function initContainers(settings: Settings): Promise<void> {
  const client = getCosmosClient(settings);

  await client.databases.createIfNotExists({ id: settings.COSMOS_DB_DATABASE });
  logger.info(`데이터베이스 확인/생성 완료: ${settings.COSMOS_DB_DATABASE}`);

  const database = client.database(settings.COSMOS_DB_DATABASE);

  for (const defn of CONTAINER_DEFINITIONS) {
    const containerDef: Record<string, unknown> = {
      id: defn.id,
      partitionKey: { paths: [defn.partitionKey] } as PartitionKeyDefinition,
    };

    if (defn.ttl !== null) {
      containerDef.defaultTtl = defn.ttl;
    }

    if (defn.indexingPolicy !== null) {
      containerDef.indexingPolicy = defn.indexingPolicy;
    }

    await database.containers.createIfNotExists(
      containerDef as { id: string; partitionKey: PartitionKeyDefinition },
    );
    logger.info(`컨테이너 확인/생성 완료: ${defn.id}`);
  }
}

export function closeClient(): void {
  if (_client) {
    _client.dispose();
    _client = null;
    _database = null;
    logger.info('Cosmos DB 클라이언트 연결 종료');
  }
}

export function resetClient(): void {
  _client = null;
  _database = null;
}
