export const MATERIAL_LIMIT = 20_000;
export const MATERIAL_FILE_LIMIT = 10 * 1024 * 1024;
export type MaterialPreview = {filename:string;format:string;text:string;characters:number;pages:number|null;warnings:string[];max_characters:number};

export function importedMaterial(current:string,text:string,filename:string,mode:'append'|'replace'):string {
  if(!text.trim())throw new Error('提取内容为空，请补充文字后再填入。');
  const content=`资料内容：\n${text.trim()}\n资料来源：上传文件《${filename}》`;
  if(mode==='append'&&current.includes(content))throw new Error('当前资料已包含这份导入内容，无需重复追加。');
  const result=mode==='append'&&current.trim()?current.trimEnd()+'\n\n'+content:content;
  if(result.length>MATERIAL_LIMIT)throw new Error('填入后将超过2万字，请精简预览内容或选择替换原资料；原资料已保留。');
  return result;
}
