import test from 'node:test';
import assert from 'node:assert/strict';
import {importedMaterial,MATERIAL_LIMIT} from './material-state.ts';

test('append preserves edited material and resets a previous source section for imported facts',()=>{
  const original='老师已核对的原资料。\n资料来源：原有来源';
  const result=importedMaterial(original,'保国寺大殿重建于1013年。','history.docx','append');
  assert.ok(result.startsWith(original+'\n\n资料内容：\n'));
  assert.ok(result.includes('1013年'));
  assert.ok(result.endsWith('资料来源：上传文件《history.docx》'));
});
test('replacement requires an explicit mode and keeps only the reviewed imported text and source',()=>{
  const result=importedMaterial('原资料',' 修改后的提取文字。 ','course.pdf','replace');
  assert.ok(!result.includes('原资料'));
  assert.ok(result.includes('修改后的提取文字。'));
  assert.ok(result.includes('course.pdf'));
});
test('empty previews, duplicate appends and overflow fail instead of losing or truncating material',()=>{
  assert.throws(()=>importedMaterial('原资料','  ','file.txt','append'),/为空/);
  const first=importedMaterial('原资料','1013年重建。','file.txt','append');
  assert.throws(()=>importedMaterial(first,'1013年重建。','file.txt','append'),/无需重复追加/);
  assert.throws(()=>importedMaterial('原资料','文'.repeat(MATERIAL_LIMIT),'file.txt','append'),/原资料已保留/);
});
