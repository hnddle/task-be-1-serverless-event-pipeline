/**
 * Cosmos DB 데이터베이스 및 컨테이너 초기화 스크립트.
 *
 * local.settings.json에서 환경변수를 읽어 Cosmos DB에 데이터베이스와 컨테이너를 생성한다.
 * 사용법: node scripts/init-db.js
 */

const fs = require('fs');
const path = require('path');

// local.settings.json 로드 → process.env에 주입
const settingsPath = path.join(__dirname, '..', 'local.settings.json');
const settings = JSON.parse(fs.readFileSync(settingsPath, 'utf8'));
Object.entries(settings.Values || {}).forEach(([k, v]) => {
  process.env[k] = v;
});

// 빌드된 JS에서 import
async function main() {
  const { initContainers, closeClient } = require('../dist/src/services/cosmos-client');
  const { loadSettings } = require('../dist/src/shared/config');

  console.log('Cosmos DB 초기화 시작...');
  const s = loadSettings();
  console.log(`Endpoint: ${s.COSMOS_DB_ENDPOINT}`);
  console.log(`Database: ${s.COSMOS_DB_DATABASE}`);

  await initContainers(s);
  console.log('초기화 완료! 6개 컨테이너가 생성되었습니다.');
  closeClient();
}

main().catch((err) => {
  console.error('초기화 실패:', err);
  process.exit(1);
});
