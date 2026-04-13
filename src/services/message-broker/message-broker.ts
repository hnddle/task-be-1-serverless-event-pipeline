/**
 * Message Broker 추상 인터페이스.
 *
 * 메시지 큐를 교체 가능한 Backing Service로 취급한다.
 * SPEC.md §4.1 참조.
 */

export interface MessageBroker {
  publish(event: Record<string, unknown>): Promise<void>;
  getBrokerName(): string;
}
