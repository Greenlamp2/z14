import time
import audioop
import threading
from collections import deque
import discord


class RecorderStream(object):
    def __init__(self, user_id):

        self.user_id = user_id
        self.decoder = discord.opus.Decoder(48000, 2)

        self.stream = deque()
        self.ready = False

        self.lock = threading.Lock()
        self.decoder_lock = threading.Lock()
        self.sequence = -1
        self.waiting = []
        self.buffering = 1
        self.silence = 0
        self.i = 0

    def append(self, data, sequence, timestamp):

        silence = data == b"\xF8\xFF\xFE"

        with self.decoder_lock:
            pcm = self.decoder.decode(data, self.decoder.samples_per_frame)
            self.i += 1

        if silence:
            maxlevel = 0
        else:
            maxlevel = audioop.max(pcm, 2) / (2 ** 16)

        with self.lock:
            self.waiting.append((pcm, sequence, timestamp, maxlevel, silence))

    def update(self):

        with self.lock:

            n_waiting = len(self.waiting)

            if n_waiting == 0 or self.buffering:
                self.buffering += 1

                if n_waiting < 4:
                    return

            # choose next chunk
            sequences = sorted([(i, t[1]) for i, t in enumerate(self.waiting)], key=lambda a: a[1])
            next_up = [s for s in sequences if s[1] > self.sequence]
            if next_up:
                chunk_i = next_up[0][0]
            else:
                chunk_i = sequences[0][0]
            next_sequence = sequences[chunk_i][1]

            # determine if packets were lost (or there was silence)
            if next_sequence < self.sequence - 8192:
                skipped = next_sequence - (self.sequence - 2 ** 16) - 1
                print("wrapped around", self.sequence, next_sequence, skipped)
            else:
                skipped = next_sequence - self.sequence - 1
            skipped -= self.silence

            if skipped > 0:
                for i in range(min(skipped, 1)):
                    try:
                        previous = self.stream[-1]
                        # previous packet was silence
                        if (previous and previous[-1]):
                            # fill in with silence
                            self.stream.append(None)
                        else:
                            # lost packet - fill with previous data
                            self.stream.append(self.stream[-1])
                    except IndexError:
                        self.stream.append(None)

            self.sequence = next_sequence
            self.buffering = 0
            self.silence = 0
            popped = self.waiting.pop(chunk_i)
            self.stream.append(popped)


class Recorder(threading.Thread):
    def __init__(self):

        super().__init__()

        self.output = deque()
        self.lock = threading.Lock()

        self.frames_per_second = 50
        self.interval = 1 / self.frames_per_second
        self.duration = 20

        # keyed by user id
        self.streams = {}
        self.streams_lock = threading.Lock()

        self.silence = b"\x00" * 3840

    def receive_packet(self, data, user_id, sequence, timestamp):

        if not user_id:
            return

        # if random.uniform(0,1) < 0.25:
        #   packet loss
        #	return

        with self.streams_lock:
            if not user_id in self.streams:
                self.streams[user_id] = RecorderStream(user_id)

        self.streams[user_id].append(data, sequence, timestamp)

    def run(self):

        start_time = time.time()
        sequence = 0

        while True:

            sequence += 1
            wait = (start_time + sequence * self.interval) - time.time()
            if wait > 1 or wait < -1:
                start_time -= wait
                wait = 0
            time.sleep(max((sequence % 2) * 0.001, wait))

            chunks = []
            lengths = []

            with self.streams_lock:
                streams = list(self.streams)

            # Collect a chunk for each speaker
            for key in sorted(streams):
                self.streams[key].update()

                lengths.append(len(self.streams[key].stream))
                if self.streams[key].i < 10:
                    continue

                try:
                    chunk = self.streams[key].stream.popleft()
                except IndexError:
                    chunk = None
                if chunk is not None:
                    chunks.append(chunk)

            if lengths and max(lengths) > 25 and sequence % 5 == 0:
                print("long buffers in recorder", lengths)

            if chunks:
                with self.lock:
                    self.output.append(chunks)

                    if len(self.output) > self.duration * self.frames_per_second:
                        self.output.popleft()

                    """
                    EXAMPLE: Mix all speakers together, dump to disk. NOT TESTED. 

                    The output file could be converted to WAV using something like this:
                    ffmpeg -f s16le -ar 48000 -i <filename> converted.mp3 

                    multiplier = 0.333
                    mix = None
                    for i, (pcm, sequence, timestamp, maxlevel, silence) in enumerate( chunks ):
                        # Make the speaker quieter. 
                        # Without this, the final mix could clip when people speak simultaneously. 
                        # I recommend you write something fancier, where the multiplier 
                        # is adjusted over time based on the number of speakers (len(chunks)). 
                        # You could also use maxlevel to normalize volume per speaker.
                        multiplied_pcm = audioop.mul( pcm, 2, multiplier )

                        if i == 0:
                            mix = multiplied_pcm
                        else:
                            # Overlay speaker's audio to the mix
                            mix = audioop.add( mix, multiplied_pcm, 2 )

                    # Write PCM to disk.
                    # You need to open a file handle before the loop or something :)
                    fh.write( mix )

                    """

    def get_replay(self, duration, padding=0, trim_silence=False):

        with self.lock:
            clone = list(self.output)

        b = max(1, int(padding * self.frames_per_second))
        a = int(duration * self.frames_per_second)

        select = clone[-(a + b): -b]

        if trim_silence:
            for i in range(min(min(50, len(select)), duration * self.frames_per_second - 10)):
                for speaker in select[i]:
                    if speaker[-2] > 0.05:
                        i = max(0, i - 10)
                        break
            select = select[i:]

        return select

    def reset(self):
        pass
