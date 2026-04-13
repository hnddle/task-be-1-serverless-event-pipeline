/**
 * Cosmos DB 클라이언트 싱글턴 및 컨테이너 참조 테스트.
 */

import type { Settings } from '@src/shared/config';

jest.mock('@azure/cosmos', () => {
  const mockContainer = { id: 'mock-container' };
  const mockDatabase = {
    container: jest.fn(() => mockContainer),
    containers: { createIfNotExists: jest.fn() },
  };
  const mockClient = {
    database: jest.fn(() => mockDatabase),
    databases: { createIfNotExists: jest.fn().mockResolvedValue({}) },
    dispose: jest.fn(),
  };
  const MockCosmosClient = jest.fn(() => mockClient);

  return {
    CosmosClient: MockCosmosClient,
    __mockClient: mockClient,
    __mockDatabase: mockDatabase,
    __mockContainer: mockContainer,
  };
});

import {
  CONTAINER_DEFINITIONS,
  closeClient,
  getCircuitBreakerContainer,
  getContainer,
  getCosmosClient,
  getDatabase,
  getDlqContainer,
  getEventsContainer,
  getLeasesContainer,
  getRateLimiterContainer,
  initContainers,
  resetClient,
} from '@src/services/cosmos-client';
import { CosmosClient } from '@azure/cosmos';

const cosmos = jest.requireMock('@azure/cosmos') as {
  CosmosClient: jest.Mock;
  __mockClient: {
    database: jest.Mock;
    databases: { createIfNotExists: jest.Mock };
    dispose: jest.Mock;
    [key: string]: unknown;
  };
  __mockDatabase: {
    container: jest.Mock;
    containers: { createIfNotExists: jest.Mock };
    [key: string]: unknown;
  };
};

const REQUIRED_ENV: Record<string, string> = {
  QUEUE_SERVICE_TYPE: 'EVENT_GRID',
  NOTIFICATION_EMAIL_PROVIDER: 'sendgrid',
  NOTIFICATION_SMS_PROVIDER: 'twilio',
  WEBHOOK_URL: 'https://example.com/webhook',
  COSMOS_DB_ENDPOINT: 'https://localhost:8081',
  COSMOS_DB_KEY: 'test-key',
  COSMOS_DB_DATABASE: 'test-db',
};

function makeSettings(): Settings {
  return {
    QUEUE_SERVICE_TYPE: REQUIRED_ENV.QUEUE_SERVICE_TYPE,
    NOTIFICATION_EMAIL_PROVIDER: REQUIRED_ENV.NOTIFICATION_EMAIL_PROVIDER,
    NOTIFICATION_SMS_PROVIDER: REQUIRED_ENV.NOTIFICATION_SMS_PROVIDER,
    WEBHOOK_URL: REQUIRED_ENV.WEBHOOK_URL,
    COSMOS_DB_ENDPOINT: REQUIRED_ENV.COSMOS_DB_ENDPOINT,
    COSMOS_DB_KEY: REQUIRED_ENV.COSMOS_DB_KEY,
    COSMOS_DB_DATABASE: REQUIRED_ENV.COSMOS_DB_DATABASE,
    CB_FAILURE_THRESHOLD: 5,
    CB_COOLDOWN_MS: 30000,
    CB_SUCCESS_THRESHOLD: 2,
    MAX_RETRY_COUNT: 3,
    RETRY_BASE_DELAY_MS: 1000,
    RETRY_BACKOFF_MULTIPLIER: 2,
    RATE_LIMIT_EMAIL_PER_SEC: 10,
    RATE_LIMIT_SMS_PER_SEC: 5,
    RATE_LIMIT_WEBHOOK_PER_SEC: 20,
    RATE_LIMIT_MAX_WAIT_MS: 10000,
    MOCK_DELAY_MIN_MS: 100,
    MOCK_DELAY_MAX_MS: 500,
    EVENT_GRID_TOPIC_ENDPOINT: 'https://test-topic.koreacentral-1.eventgrid.azure.net/api/events',
    EVENT_GRID_TOPIC_KEY: 'test-key',
  };
}

beforeEach(() => {
  resetClient();
  jest.clearAllMocks();
});

afterEach(() => {
  resetClient();
});

describe('Cosmos Client 싱글턴', () => {
  it('get_cosmos_client를 여러 번 호출해도 클라이언트는 한 번만 생성된다', () => {
    const settings = makeSettings();
    const client1 = getCosmosClient(settings);
    const client2 = getCosmosClient(settings);
    expect(client1).toBe(client2);
    expect(CosmosClient).toHaveBeenCalledTimes(1);
  });

  it('클라이언트가 Settings의 endpoint와 key를 사용한다', () => {
    const settings = makeSettings();
    getCosmosClient(settings);
    expect(CosmosClient).toHaveBeenCalledWith({
      endpoint: 'https://localhost:8081',
      key: 'test-key',
    });
  });

  it('getDatabase가 데이터베이스 참조를 반환한다', () => {
    const settings = makeSettings();
    getDatabase(settings);
    expect(cosmos.__mockClient.database).toHaveBeenCalledWith('test-db');
  });

  it('getDatabase를 여러 번 호출해도 동일 참조를 반환한다', () => {
    const settings = makeSettings();
    const db1 = getDatabase(settings);
    const db2 = getDatabase(settings);
    expect(db1).toBe(db2);
    expect(cosmos.__mockClient.database).toHaveBeenCalledTimes(1);
  });

  it('resetClient가 싱글턴 상태를 초기화한다', () => {
    const settings = makeSettings();
    getCosmosClient(settings);
    resetClient();
    getCosmosClient(settings);
    expect(CosmosClient).toHaveBeenCalledTimes(2);
  });
});

describe('컨테이너 참조 함수', () => {
  it('getContainer가 올바른 컨테이너 참조를 반환한다', () => {
    const settings = makeSettings();
    getContainer(settings, 'events');
    expect(cosmos.__mockDatabase.container).toHaveBeenCalledWith('events');
  });

  it('유효하지 않은 컨테이너 이름이면 에러가 발생한다', () => {
    const settings = makeSettings();
    expect(() => getContainer(settings, 'invalid-container')).toThrow('알 수 없는 컨테이너');
  });

  it('getEventsContainer가 events 컨테이너를 반환한다', () => {
    const settings = makeSettings();
    getEventsContainer(settings);
    expect(cosmos.__mockDatabase.container).toHaveBeenCalledWith('events');
  });

  it('getDlqContainer가 dead-letter-queue 컨테이너를 반환한다', () => {
    const settings = makeSettings();
    getDlqContainer(settings);
    expect(cosmos.__mockDatabase.container).toHaveBeenCalledWith('dead-letter-queue');
  });

  it('getCircuitBreakerContainer가 circuit-breaker 컨테이너를 반환한다', () => {
    const settings = makeSettings();
    getCircuitBreakerContainer(settings);
    expect(cosmos.__mockDatabase.container).toHaveBeenCalledWith('circuit-breaker');
  });

  it('getRateLimiterContainer가 rate-limiter 컨테이너를 반환한다', () => {
    const settings = makeSettings();
    getRateLimiterContainer(settings);
    expect(cosmos.__mockDatabase.container).toHaveBeenCalledWith('rate-limiter');
  });

  it('getLeasesContainer가 leases 컨테이너를 반환한다', () => {
    const settings = makeSettings();
    getLeasesContainer(settings);
    expect(cosmos.__mockDatabase.container).toHaveBeenCalledWith('leases');
  });
});

describe('컨테이너 정의 상수', () => {
  it('6개 컨테이너가 정의되어 있다', () => {
    expect(CONTAINER_DEFINITIONS).toHaveLength(6);
  });

  it('올바른 컨테이너 이름들이 정의되어 있다', () => {
    const names = new Set(CONTAINER_DEFINITIONS.map((d) => d.id));
    expect(names).toEqual(
      new Set(['events', 'dead-letter-queue', 'circuit-breaker', 'rate-limiter', 'leases', 'logs']),
    );
  });

  it('events 컨테이너의 Partition Key가 /clinic_id이다', () => {
    const events = CONTAINER_DEFINITIONS.find((d) => d.id === 'events')!;
    expect(events.partitionKey).toBe('/clinic_id');
  });

  it('dead-letter-queue 컨테이너의 Partition Key가 /clinic_id이다', () => {
    const dlq = CONTAINER_DEFINITIONS.find((d) => d.id === 'dead-letter-queue')!;
    expect(dlq.partitionKey).toBe('/clinic_id');
  });

  it('circuit-breaker 컨테이너의 Partition Key가 /id이다', () => {
    const cb = CONTAINER_DEFINITIONS.find((d) => d.id === 'circuit-breaker')!;
    expect(cb.partitionKey).toBe('/id');
  });

  it('rate-limiter 컨테이너의 Partition Key가 /id이다', () => {
    const rl = CONTAINER_DEFINITIONS.find((d) => d.id === 'rate-limiter')!;
    expect(rl.partitionKey).toBe('/id');
  });

  it('rate-limiter 컨테이너의 TTL이 60초이다', () => {
    const rl = CONTAINER_DEFINITIONS.find((d) => d.id === 'rate-limiter')!;
    expect(rl.ttl).toBe(60);
  });

  it('rate-limiter, logs 이외 컨테이너는 TTL이 없다', () => {
    const others = CONTAINER_DEFINITIONS.filter((d) => d.id !== 'rate-limiter' && d.id !== 'logs');
    for (const defn of others) {
      expect(defn.ttl).toBeNull();
    }
  });

  it('logs 컨테이너의 Partition Key가 /correlation_id이다', () => {
    const logs = CONTAINER_DEFINITIONS.find((d) => d.id === 'logs')!;
    expect(logs.partitionKey).toBe('/correlation_id');
  });

  it('logs 컨테이너의 TTL이 604800초(7일)이다', () => {
    const logs = CONTAINER_DEFINITIONS.find((d) => d.id === 'logs')!;
    expect(logs.ttl).toBe(604800);
  });

  it('events 컨테이너에 status, event_type, created_at 복합 인덱스가 있다', () => {
    const events = CONTAINER_DEFINITIONS.find((d) => d.id === 'events')!;
    const policy = events.indexingPolicy as Record<string, unknown>;
    expect(policy).toBeDefined();
    const composites = (policy.compositeIndexes as { path: string }[][]);
    expect(composites).toHaveLength(1);
    const paths = composites[0].map((idx) => idx.path);
    expect(paths).toEqual(['/status', '/event_type', '/created_at']);
  });
});

describe('initContainers 함수', () => {
  it('initContainers가 데이터베이스와 6개 컨테이너를 생성한다', async () => {
    const settings = makeSettings();
    await initContainers(settings);

    expect(cosmos.__mockClient.databases.createIfNotExists).toHaveBeenCalledWith({
      id: 'test-db',
    });

    const db = cosmos.__mockClient.database();
    expect(db.containers.createIfNotExists).toHaveBeenCalledTimes(6);
  });
});

describe('closeClient 함수', () => {
  it('closeClient가 클라이언트를 종료하고 싱글턴을 초기화한다', () => {
    const settings = makeSettings();
    getCosmosClient(settings);
    closeClient();

    expect(cosmos.__mockClient.dispose).toHaveBeenCalledTimes(1);

    // 싱글턴이 초기화되어 다시 생성됨
    getCosmosClient(settings);
    expect(CosmosClient).toHaveBeenCalledTimes(2);
  });

  it('클라이언트가 초기화되지 않은 상태에서 closeClient를 호출해도 에러가 없다', () => {
    expect(() => closeClient()).not.toThrow();
  });
});
