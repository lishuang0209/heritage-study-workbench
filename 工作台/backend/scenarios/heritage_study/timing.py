from pydantic import BaseModel, ConfigDict, Field, model_validator


class Timing(BaseModel):
    model_config = ConfigDict(extra='forbid')
    intro: int = Field(default=12, ge=3, le=180, strict=True)
    location: int = Field(default=11, ge=3, le=180, strict=True)
    task: int = Field(default=7, ge=3, le=180, strict=True)

    @model_validator(mode='after')
    def total_limit(self):
        if self.intro+self.location+self.task > 300:
            raise ValueError('总时长不能超过300秒')
        return self


def timing_for(project):
    return Timing.model_validate(project.get('heritage_timing') or {}).model_dump()


def observation_slots(seconds, detail):
    if not detail: return [('panorama', seconds)]
    panorama = (seconds*6+10)//11
    return [('panorama', panorama), ('detail', seconds-panorama)]
