"""VideoToolbox H.264 for macOS; retain aiortc packetization and software fallback."""
import fractions
import sys
import av
from utils.logger import logger


def install_apple_h264():
    if sys.platform != 'darwin' or 'h264_videotoolbox' not in av.codecs_available:
        return False
    import aiortc.codecs
    from aiortc.codecs.h264 import H264Encoder, MAX_FRAME_RATE

    class AppleH264Encoder(H264Encoder):
        def _encode_frame(self, frame, force_keyframe):
            if getattr(self, '_software_fallback', False):
                yield from super()._encode_frame(frame, force_keyframe)
                return
            if self.codec and (frame.width != self.codec.width or frame.height != self.codec.height
                               or abs(self.target_bitrate-self.codec.bit_rate)/self.codec.bit_rate > 0.1):
                self.buffer_data = b''
                self.buffer_pts = None
                self.codec = None
            frame.pict_type = av.video.frame.PictureType.I if force_keyframe else av.video.frame.PictureType.NONE
            try:
                if self.codec is None:
                    self.codec = av.CodecContext.create('h264_videotoolbox', 'w')
                    self.codec.width, self.codec.height = frame.width, frame.height
                    self.codec.bit_rate = self.target_bitrate
                    self.codec.pix_fmt = 'yuv420p'
                    self.codec.framerate = fractions.Fraction(MAX_FRAME_RATE, 1)
                    self.codec.time_base = fractions.Fraction(1, MAX_FRAME_RATE)
                    self.codec.profile = 'Baseline'
                    self.codec.max_b_frames = 0
                    self.codec.options = {'realtime': '1', 'allow_sw': '0'}
                    logger.info('VideoToolbox H264 encoding %sx%s', frame.width, frame.height)
                data = b''.join(bytes(packet) for packet in self.codec.encode(frame))
            except av.FFmpegError as exc:
                logger.warning('VideoToolbox unavailable, falling back to software H264: %s', exc)
                self.codec = None
                self._software_fallback = True
                yield from super()._encode_frame(frame, True)
                return
            if data:
                yield from self._split_bitstream(data)

    aiortc.codecs.H264Encoder = AppleH264Encoder
    logger.info('Apple VideoToolbox hardware H264 encoding enabled')
    return True
