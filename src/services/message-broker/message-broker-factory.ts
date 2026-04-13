/**
 * Message Broker 팩토리.
 *
 * 환경 변수 QUEUE_SERVICE_TYPE에 따라 적절한 MessageBroker 어댑터를 생성한다.
 * SPEC.md §4.1 참조.
 */

import { AzureKeyCredential } from '@azure/eventgrid';
import type { Settings } from '../../shared/config';
import { EventGridAdapter } from './event-grid-adapter';
import type { MessageBroker } from './message-broker';

const SUPPORTED_BROKER_TYPES = new Set(['EVENT_GRID']);

export class MessageBrokerFactory {
  static create(settings: Settings): MessageBroker {
    const brokerType = settings.QUEUE_SERVICE_TYPE.toUpperCase();

    if (brokerType === 'EVENT_GRID') {
      const extSettings = settings as unknown as Record<string, string>;
      const endpoint = extSettings.EVENT_GRID_ENDPOINT ?? '';
      const key = extSettings.EVENT_GRID_KEY ?? '';
      const credential = new AzureKeyCredential(key);
      return new EventGridAdapter(endpoint, credential);
    }

    const supported = [...SUPPORTED_BROKER_TYPES].sort().join(', ');
    throw new Error(
      `지원하지 않는 QUEUE_SERVICE_TYPE: '${settings.QUEUE_SERVICE_TYPE}'. 지원: ${supported}`,
    );
  }
}
