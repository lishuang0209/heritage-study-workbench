import type { Dialogue, Project } from './ink-shared';

export const NARRATOR = 'narrator';

export function speakerName(characters:{id:string;name:string}[], id:string):string {
  return id === NARRATOR ? '旁白' : characters.find(character=>character.id===id)?.name || '角色';
}

export function retainDialogues(lines:Dialogue[], visibleIds:string[]):Dialogue[] {
  return lines.filter(line=>line.character_id===NARRATOR || visibleIds.includes(line.character_id));
}

export function voiceSpeakers(project:Pick<Project,'characters'>):{id:string;name:string}[] {
  return [...project.characters.map(({id,name})=>({id,name})), {id:NARRATOR,name:'旁白（画外音）'}];
}
