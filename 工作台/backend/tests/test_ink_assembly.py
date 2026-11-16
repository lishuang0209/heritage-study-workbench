"""Mixed generated and narrated clips must remain visible in the right order."""
import re
import subprocess

from scenarios.ink_drama.providers import Providers, checked_ffmpeg, ffmpeg_executable


def test_mixed_frame_rates_audio_formats_and_silent_shots_keep_every_shot(tmp_path):
    provider = Providers()
    colors = [('red',(255,0,0)),('green',(0,128,0)),('blue',(0,0,255)),
              ('yellow',(255,255,0)),('magenta',(255,0,255)),('cyan',(0,255,255))]
    durations = [2,3,2,2,3,2]
    clips = []
    for i, ((color, _), duration) in enumerate(zip(colors, durations)):
        path = tmp_path / f'part-{i}.mp4'
        fps = 24 if i in (0,3) else 30
        rate = 48000 if fps == 24 else 44100
        size = '180x320' if fps == 24 else '240x426'
        inputs = ['-f','lavfi','-i',f'color=c={color}:s={size}:r={fps}:d={duration}']
        if i != 3:
            inputs += ['-f','lavfi','-i',f'sine=frequency={220+i*100}:sample_rate={rate}:duration={duration}']
        checked_ffmpeg([*inputs,'-c:v','libx264','-pix_fmt','yuv420p','-c:a','aac',str(path)])
        clips.append(path)
    target = tmp_path/'final.mp4'
    provider.assemble(clips, None, tmp_path, target)
    assert abs(provider.duration(target) - sum(durations)) < .1
    elapsed = 0
    for (_, rgb), duration in zip(colors, durations):
        # Verify each shot, including the silent fourth shot, across its interval.
        for offset in (.2, duration/2, duration-.2):
            pixel = subprocess.check_output([ffmpeg_executable(),'-v','error','-ss',str(elapsed+offset),
                '-i',str(target),'-frames:v','1','-vf','scale=1:1','-pix_fmt','rgb24','-f','rawvideo','pipe:1'])
            assert len(pixel) == 3
            assert max(abs(a-b) for a,b in zip(pixel,rgb)) < 15
        elapsed += duration
    decoded = subprocess.run([ffmpeg_executable(),'-hide_banner','-i',str(target),
        '-vf','showinfo','-an','-f','null','-'],capture_output=True,text=True)
    assert decoded.returncode == 0
    assert 'non monotonically increasing' not in decoded.stderr
    timestamps = [float(x) for x in re.findall(r'pts_time:([\d.]+)',decoded.stderr)]
    assert len(timestamps) == sum(durations)*30
    assert all(a < b for a,b in zip(timestamps,timestamps[1:]))
