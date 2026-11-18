import type {Project, Shot} from '../ink-shared';
const NARRATOR='narrator';

export type NarrationProfile={voice:string;label:string;speed:number};
const profiles:NarrationProfile[]=[
 {voice:'zh-CN-XiaoxiaoNeural',label:'晓晓 · 亲切女声（推荐）',speed:.95},
 {voice:'zh-CN-YunxiaNeural',label:'云夏 · 小学生男声',speed:1},
 {voice:'zh-CN-YunxiNeural',label:'云希 · 自然男声',speed:.95},
 {voice:'zh-CN-YunjianNeural',label:'云健 · 沉稳男声',speed:1},
];
export function studyNarration(p:Pick<Project,'voices'|'heritage_narration'>) {
 if(p.heritage_narration)return p.heritage_narration;
 return {...(profiles.find(item=>item.voice===p.voices?.[NARRATOR])||profiles[0]),choices:profiles};
}
export function voiceChoice(p:Pick<Project,'characters'|'voices'>,voice:string):Record<string,string> {
 return Object.fromEntries([...p.characters.map(c=>[c.id,p.voices?.[c.id]||(c.id==='c2'?'zh-CN-XiaoxiaoNeural':'zh-CN-YunjianNeural')]),[NARRATOR,voice]]);
}
export function unifiedNarration(p:Pick<Project,'project_type'>,shot:Pick<Shot,'dialogues'>|undefined) {
 return p.project_type==='heritage'&&Boolean(shot?.dialogues.some(line=>line.character_id===NARRATOR));
}
