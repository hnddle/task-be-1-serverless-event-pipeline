/**
 * Message Broker 팩토리.
 *
 * 환경 변수 QUEUE_SERVICE_TYPE에 따라 적절한 MessageBroker 어댑터를 생성한다.
 * SPEC.md §4.1 참조.
 */

import { AzureKeyCredential } from '@azure/eventgrid';
import type { Settings } from '../../shared/config';
import { getLogger } from '../../shared/logger';
import { EventGridAdapter } from './event-grid-adapter';
import type { MessageBroker } from './message-broker';

const logger = getLogger('message-broker-factory');

const SUPPORTED_BROKER_TYPES = new Set(['EVENT_GRID']);

export class MessageBrokerFactory {
  static create(settings: Settings): MessageBroker {
    const brokerType = settings.QUEUE_SERVICE_TYPE.toUpperCase();

    if (brokerType === 'EVENT_GRID') {
      const endpoint = settings.EVENT_GRID_TOPIC_ENDPOINT;
      const key = settings.EVENT_GRID_TOPIC_KEY;

      if (!endpoint || !key) {
        logger.error('EVENT_GRID_TOPIC_ENDPOINT 또는 EVENT_GRID_TOPIC_KEY 미설정', {
          has_endpoint: !!endpoint,
          has_key: !!key,
        });
        throw new Error(
          'QUEUE_SERVICE_TYPE=EVENT_GRID이지만 EVENT_GRID_TOPIC_ENDPOINT/EVENT_GRID_TOPIC_KEY가 설정되지 않았습니다.',
        );
      }

      const credential = new AzureKeyCredential(key);
      return new EventGridAdapter(endpoint, credential);
    }

    const supported = [...SUPPORTED_BROKER_TYPES].sort().join(', ');
    throw new Error(
      `지원하지 않는 QUEUE_SERVICE_TYPE: '${settings.QUEUE_SERVICE_TYPE}'. 지원: ${supported}`,
    );
  }
}
