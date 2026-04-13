/**
 * Cosmos DB 데이터베이스 및 컨테이너 초기화 스크립트.
 *
 * 사용법: npx ts-node -r tsconfig-paths/register scripts/init-db.ts
 */

import { initContainers, closeClient } from '../src/services/cosmos-client';
import { loadSettings } from '../src/shared/config';

async function main(): Promise<void> {
  console.log('Cosmos DB 초기화 시작...');

  const settings = loadSettings();
  console.log(`Endpoint: ${settings.COSMOS_DB_ENDPOINT}`);
  console.log(`Database: ${settings.COSMOS_DB_DATABASE}`);

  await initContainers(settings);

  console.log('초기화 완료! 5개 컨테이너가 생성되었습니다.');
  closeClient();
}

main().catch((err) => {
  console.error('초기화 실패:', err);
  process.exit(1);
});
