#
# Copyright Contributors to the OpenTimelineIO project
#
# Licensed under the Apache License, Version 2.0 (the "Apache License")
# with the following modification; you may not use this file except in
# compliance with the Apache License and the following modification to it:
# Section 6. Trademarks. is deleted and replaced with:
#
# 6. Trademarks. This License does not grant permission to use the trade
#    names, trademarks, service marks, or product names of the Licensor
#    and its affiliates, except as required to comply with Section 4(c) of
#    the License and to reproduce the content of the NOTICE file.
#
# You may obtain a copy of the Apache License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the Apache License with the above modification is
# distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied. See the Apache License for the specific
# language governing permissions and limitations under the Apache License.
#


import os
import re
import hiero.core
import hiero.ui
import opentimelineio as otio


class _Hiero_otio(object):
    pass


# build modul class
_hotio = _Hiero_otio()

_hotio.marker_color_map = {
    "magenta": otio.schema.MarkerColor.MAGENTA,
    "red": otio.schema.MarkerColor.RED,
    "yellow": otio.schema.MarkerColor.YELLOW,
    "green": otio.schema.MarkerColor.GREEN,
    "cyan": otio.schema.MarkerColor.CYAN,
    "blue": otio.schema.MarkerColor.BLUE,
}
_hotio.hiero_sequence = None
_hotio.include_tags = None


def get_rate(item):
    if not hasattr(item, 'framerate'):
        item = item.sequence()

    num, den = item.framerate().toRational()
    rate = float(num) / float(den)

    if rate.is_integer():
        return rate

    return round(rate, 2)


def get_clip_ranges(trackitem):
    # Get rate from source or sequence
    if trackitem.source().mediaSource().hasVideo():
        rate_item = trackitem.source()

    else:
        rate_item = trackitem.sequence()

    source_rate = get_rate(rate_item)

    # Reversed video/audio
    if trackitem.playbackSpeed() < 0:
        start = trackitem.sourceOut()

    else:
        start = trackitem.sourceIn()

    source_start_time = otio.opentime.RationalTime(
        start,
        source_rate
    )
    source_duration = otio.opentime.RationalTime(
        trackitem.duration(),
        source_rate
    )

    source_range = otio.opentime.TimeRange(
        start_time=source_start_time,
        duration=source_duration
    )

    hiero_clip = trackitem.source()

    available_range = None
    if hiero_clip.mediaSource().isMediaPresent():
        start_time = otio.opentime.RationalTime(
            hiero_clip.mediaSource().startTime(),
            source_rate
        )
        duration = otio.opentime.RationalTime(
            hiero_clip.mediaSource().duration(),
            source_rate
        )
        available_range = otio.opentime.TimeRange(
            start_time=start_time,
            duration=duration
        )

    return source_range, available_range


def add_gap(trackitem, otio_track, prev_out):
    gap_length = trackitem.timelineIn() - prev_out
    if prev_out != 0:
        gap_length -= 1

    rate = get_rate(trackitem.sequence())
    gap = otio.opentime.TimeRange(
        duration=otio.opentime.RationalTime(
            gap_length,
            rate
        )
    )
    otio_gap = otio.schema.Gap(source_range=gap)
    otio_track.append(otio_gap)


def get_marker_color(tag):
    icon = tag.icon()
    pat = r'icons:Tag(?P<color>\w+)\.\w+'

    res = re.search(pat, icon)
    if res:
        color = res.groupdict().get('color')
        if color.lower() in _hotio.marker_color_map:
            return _hotio.marker_color_map[color.lower()]

    return otio.schema.MarkerColor.RED


def add_markers(hiero_item, otio_item):
    for tag in hiero_item.tags():
        if not tag.visible():
            continue

        if tag.name() == 'Copy':
            # Hiero adds this tag to a lot of clips
            continue

        frame_rate = get_rate(hiero_item)

        marked_range = otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(
                tag.inTime(),
                frame_rate
            ),
            duration=otio.opentime.RationalTime(
                int(tag.metadata().dict().get('tag.length', '0')),
                frame_rate
            )
        )

        metadata = dict(
            Hiero=tag.metadata().dict()
        )
        # Store the source item for future import assignment
        metadata['Hiero']['source_type'] = hiero_item.__class__.__name__

        marker = otio.schema.Marker(
            name=tag.name(),
            color=get_marker_color(tag),
            marked_range=marked_range,
            metadata=metadata
        )

        otio_item.markers.append(marker)


def add_clip(trackitem, otio_track, itemindex):
    hiero_clip = trackitem.source()

    # Add Gap if needed
    if itemindex == 0:
        prev_item = trackitem

    else:
        prev_item = trackitem.parent().items()[itemindex - 1]

    clip_diff = trackitem.timelineIn() - prev_item.timelineOut()

    if itemindex == 0 and trackitem.timelineIn() > 0:
        add_gap(trackitem, otio_track, 0)

    elif itemindex and clip_diff != 1:
        add_gap(trackitem, otio_track, prev_item.timelineOut())

    # Create Clip
    source_range, available_range = get_clip_ranges(trackitem)

    otio_clip = otio.schema.Clip(
        name=trackitem.name(),
        source_range=source_range
    )

    # Add media reference
    media_reference = otio.schema.MissingReference()
    if hiero_clip.mediaSource().isMediaPresent():
        source = hiero_clip.mediaSource()

        if source.singleFile():
            path = source.fileinfos()[0].filename()

            media_reference = otio.schema.ExternalReference(
                target_url=u'{}'.format(path),
                available_range=available_range
            )

        else:
            first_file = source.fileinfos()[0]
            path, basename = os.path.split(first_file.filename())
            name_prefix = source.filenameHead()
            start_frame = first_file.startFrame()
            frame_zero_padding = source.filenamePadding()
            _, name_suffix = os.path.splitext(first_file.filename())

            media_reference = otio.schema.ImageSequenceReference(
                target_url_base=path + os.sep,
                name_prefix=name_prefix,
                name_suffix=name_suffix,
                start_frame=start_frame,
                frame_zero_padding=frame_zero_padding,
                rate=available_range.start_time.rate,
                available_range=available_range

            )
    otio_clip.media_reference = media_reference

    # Add Time Effects
    playbackspeed = trackitem.playbackSpeed()
    if playbackspeed != 1:
        if playbackspeed == 0:
            time_effect = otio.schema.FreezeFrame()

        else:
            time_effect = otio.schema.LinearTimeWarp(
                time_scalar=playbackspeed
            )
        otio_clip.effects.append(time_effect)

    # Add tags as markers
    if _hotio.include_tags:
        add_markers(trackitem, otio_clip)
        add_markers(trackitem.source(), otio_clip)

    otio_track.append(otio_clip)

    # Add Transition if needed
    if trackitem.inTransition() or trackitem.outTransition():
        add_transition(trackitem, otio_track)


def add_transition(trackitem, otio_track):
    transitions = []

    if trackitem.inTransition():
        if trackitem.inTransition().alignment().name == 'kFadeIn':
            transitions.append(trackitem.inTransition())

    if trackitem.outTransition():
        transitions.append(trackitem.outTransition())

    for transition in transitions:
        alignment = transition.alignment().name

        if alignment == 'kFadeIn':
            in_offset_frames = 0
            out_offset_frames = (
                transition.timelineOut() - transition.timelineIn()
            ) + 1

        elif alignment == 'kFadeOut':
            in_offset_frames = (
                trackitem.timelineOut() - transition.timelineIn()
            ) + 1
            out_offset_frames = 0

        elif alignment == 'kDissolve':
            in_offset_frames = (
                transition.inTrackItem().timelineOut() -
                transition.timelineIn()
            )
            out_offset_frames = (
                transition.timelineOut() -
                transition.outTrackItem().timelineIn()
            )

        else:
            # kUnknown transition is ignored
            continue

        rate = trackitem.source().framerate().toFloat()
        in_time = otio.opentime.RationalTime(in_offset_frames, rate)
        out_time = otio.opentime.RationalTime(out_offset_frames, rate)

        otio_transition = otio.schema.Transition(
            name=alignment,    # Consider placing Hiero name in metadata
            transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
            in_offset=in_time,
            out_offset=out_time
        )

        if alignment == 'kFadeIn':
            otio_track.insert(-1, otio_transition)

        else:
            otio_track.append(otio_transition)


def add_tracks():
    for track in _hotio.hiero_sequence.items():
        if isinstance(track, hiero.core.AudioTrack):
            kind = otio.schema.TrackKind.Audio

        else:
            kind = otio.schema.TrackKind.Video

        otio_track = otio.schema.Track(name=track.name(), kind=kind)

        for itemindex, trackitem in enumerate(track):
            if isinstance(trackitem.source(), hiero.core.Clip):
                add_clip(trackitem, otio_track, itemindex)

        _hotio.otio_timeline.tracks.append(otio_track)

    # Add tags as markers
    if _hotio.include_tags:
        add_markers(_hotio.hiero_sequence, _hotio.otio_timeline.tracks)


def create_OTIO(sequence=None):
    _hotio.hiero_sequence = sequence or hiero.ui.activeSequence()
    _hotio.otio_timeline = otio.schema.Timeline()

    # Set global start time based on sequence
    _hotio.otio_timeline.global_start_time = otio.opentime.RationalTime(
        _hotio.hiero_sequence.timecodeStart(),
        _hotio.hiero_sequence.framerate().toFloat()
    )
    _hotio.otio_timeline.name = _hotio.hiero_sequence.name()

    add_tracks()

    return _hotio.otio_timeline
