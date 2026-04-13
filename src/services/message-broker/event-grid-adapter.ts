/**
 * Azure Event Grid 어댑터.
 *
 * @azure/eventgrid SDK를 래핑하여 MessageBroker 인터페이스를 구현한다.
 * SPEC.md §4.1 참조.
 */

import { AzureKeyCredential, EventGridPublisherClient } from '@azure/eventgrid';
import type { SendEventGridEventInput } from '@azure/eventgrid';
import { getLogger } from '../../shared/logger';
import type { MessageBroker } from './message-broker';

const logger = getLogger('event-grid-adapter');

export class EventGridAdapter implements MessageBroker {
  private readonly client: EventGridPublisherClient<'EventGrid'>;

  constructor(endpoint: string, credential: AzureKeyCredential) {
    this.client = new EventGridPublisherClient(endpoint, 'EventGrid', credential);
  }

  async publish(event: Record<string, unknown>): Promise<void> {
    const eventId = (event.id as string) ?? 'unknown';
    const egEvent: SendEventGridEventInput<Record<string, unknown>> = {
      eventType: 'NotificationPipeline.EventCreated',
      subject: `/events/${eventId}`,
      data: event,
      dataVersion: '1.0',
    };
    await this.client.send([egEvent]);
    logger.info(`Event Grid 이벤트 발행 완료: ${eventId}`);
  }

  getBrokerName(): string {
    return 'EventGrid';
  }
}
