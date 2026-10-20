export class AvatarPresentation {
  constructor() {
    const query=new URLSearchParams(location.search).get('avatar');
    this.mode=['face','body'].includes(query)?query:(localStorage.getItem('hexgf.avatarMode')||'face');
    if(!['face','body'].includes(this.mode))this.mode='face';
    this.layer=document.getElementById('av-layer');this.body=null;this.enabled=true;
    this.lastAudio=null;this.message=document.getElementById('avatar-status');
  }
  get usesVideoAudio() {return this.enabled&&this.mode==='face';}
  async setMode(mode) {
    if(!['face','body'].includes(mode))throw new Error('未知人物版本');
    this.message.textContent='正在准备人物…';
    if(mode==='body') {
      await window.DigitalAvatar?.disconnect();
      if(!this.body) {const {BodyAvatar}=await import('./body-avatar.js?v=polish-5');this.body=new BodyAvatar(this.layer);}
      await this.body.show();
      if(this.lastAudio)this.body.setAudio(...this.lastAudio);
    } else {
      this.body?.hide();
      if(this.enabled)await window.DigitalAvatar?.connect();
    }
    this.mode=mode;localStorage.setItem('hexgf.avatarMode',mode);
    const url=new URL(location.href);url.searchParams.set('avatar',mode);history.replaceState(null,'',url);
    document.body.dataset.avatarMode=mode;
    for(const button of document.querySelectorAll('[data-avatar-mode]'))button.setAttribute('aria-pressed',String(button.dataset.avatarMode===mode));
    document.getElementById('body-actions').hidden=mode!=='body';
    document.getElementById('face-character-wrap').hidden=mode!=='face';
    this.message.textContent=mode==='body'?'甜美人物 · 可挥手、走动、跳舞':'写实面部版 · 原版口型同步';
  }
  setAudio(analyser,context) {this.lastAudio=[analyser,context];this.body?.setAudio(analyser,context);}
  setStatus(status) {this.body?.setStatus(status);}
  react(transcript) {if(this.mode==='body')this.body?.react(transcript);}
  interrupt() {this.body?.interrupt();}
  gesture(action) {return this.body?.gesture(action);}
}
