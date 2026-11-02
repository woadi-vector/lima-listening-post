/* Local text decoding only. Selecting a file never sends it to the service. */
globalThis.LimaFiles = {
 decode(name, buffer) {
  const extension = name.split('.').pop().toLowerCase();
  if (!['txt', 'md', 'srt', 'vtt'].includes(extension))
   throw Error('Choose a .txt, .md, .srt, or .vtt file. Audio, video, PDF, and Word import are not available yet.');
  const bytes = new Uint8Array(buffer);
  if (!bytes.length) throw Error('This file is empty.');
  if (bytes.length > 1000000) throw Error('Choose a text file smaller than 1 MB.');
  let encoding = 'utf-8', offset = 0;
  if (bytes[0]===0xff && bytes[1]===0xfe) {encoding='utf-16le';offset=2;}
  else if (bytes[0]===0xfe && bytes[1]===0xff) {encoding='utf-16be';offset=2;}
  let text;
  try {text = new TextDecoder(encoding, {fatal:true}).decode(bytes.subarray(offset));}
  catch {throw Error('This file could not be read as Unicode text. Save it as UTF-8 text and try again.');}
  text = text.replace(/\r\n?/g, '\n');
  if (!text.trim()) throw Error('This file contains no readable text.');
  if (/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(text)) throw Error('This appears to contain binary data rather than a transcript or notes.');
  const characters = [...text].length;
  if (characters > 200000) throw Error('Choose a file with at most 200,000 characters, or split it into sections.');
  return {name, text, characters, kind:['srt','vtt'].includes(extension)?'transcript':'text'};
 }
};
