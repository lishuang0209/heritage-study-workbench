import type {CreativeSettings,Project} from '../ink-shared';

export function missingGuideReference(p:Pick<Project,'project_type'|'heritage_guide'|'shots'>,settings:CreativeSettings):boolean {
 const cid=p.heritage_guide?.character_id;
 return p.project_type==='heritage'&&Boolean(cid&&p.shots.some(shot=>shot.character_ids.includes(cid))&&!settings.characters.find(c=>c.id===cid)?.image);
}
