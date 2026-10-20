/* AudioWorklet：把标签页音频转成 16kHz 单声道 s16le PCM 分块
 *
 * 输入由 AudioNode 的 channelCount=1 / channelCountMode='explicit' 下混成立体声→单声道，
 * 所以这里 inputs[0][0] 就是单声道数据。
 *
 * 往主线程发两类消息：
 *   {type:'pcm', pcm: ArrayBuffer}   每 chunkSize 采样（默认 1024 ≈ 64ms）一包
 *   {type:'level', level: number}    RMS 电平，用于 popup 的电平条
 */
class PcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this.chunkSize = opts.chunkSize || 1024;
    this.buf = new Int16Array(this.chunkSize);
    this.offset = 0;
    this.sumSq = 0;
    this.count = 0;
    this.quanta = 0;
    this.reportEvery = 16; // ≈16*128/16000 ≈ 128ms 报一次电平
  }

  process(inputs) {
    const input = inputs[0];
    if (input && input.length && input[0]) {
      const ch = input[0];
      for (let i = 0; i < ch.length; i++) {
        let s = ch[i];
        if (s > 1) s = 1;
        else if (s < -1) s = -1;
        this.sumSq += s * s;
        this.count++;
        this.buf[this.offset++] = s < 0 ? s * 0x8000 : s * 0x7fff;
        if (this.offset >= this.chunkSize) {
          const out = new Int16Array(this.buf); // 拷贝一份再转移，避免复用踩数据
          this.port.postMessage({ type: 'pcm', pcm: out.buffer }, [out.buffer]);
          this.offset = 0;
        }
      }
    }

    if (++this.quanta >= this.reportEvery) {
      const rms = this.count ? Math.sqrt(this.sumSq / this.count) : 0;
      this.port.postMessage({ type: 'level', level: rms });
      this.quanta = 0;
      this.sumSq = 0;
      this.count = 0;
    }
    return true; // 保持节点存活
  }
}

registerProcessor('pcm-capture', PcmCaptureProcessor);
