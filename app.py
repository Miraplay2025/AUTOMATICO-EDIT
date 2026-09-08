import os
import re
import tempfile
from flask import Flask, request, jsonify
from flask_cors import CORS
import imageio_ffmpeg
import whisper

# Injeta o executável portátil do FFmpeg no PATH para o Render
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
ffmpeg_dir = os.path.dirname(ffmpeg_path)
os.environ["PATH"] += os.path.pathsep + ffmpeg_dir

app = Flask(__name__)
CORS(app)

# Carrega modelo tiny leve para rodar dentro dos 512 MB do Render Free
print("Carregando modelo OpenAI Whisper (tiny)...")
model = whisper.load_model("tiny")
print("Modelo Whisper carregado com sucesso!")

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok", "message": "Video Auto-Editor Server is running"}), 200

@app.route('/process-audio', methods=['POST'])
def process_audio():
    if 'audio' not in request.files:
        return jsonify({"status": "error", "message": "Nenhum arquivo de áudio foi fornecido. Audio é obrigatório!"}), 400
    
    audio_file = request.files['audio']
    legenda_option = request.form.get('legenda', 'nao_incluido')
    num_palavras_str = request.form.get('num_palavras', '3')
    
    try:
        words_per_group = int(num_palavras_str)
    except ValueError:
        words_per_group = 3

    # Salva arquivo temporário de áudio
    with tempfile.NamedTemporaryFile(delete=False, suffix='.mp3') as tmp:
        audio_file.save(tmp.name)
        tmp_path = tmp.name

    try:
        # Transcrição com timestamps por palavra
        result = model.transcribe(tmp_path, word_timestamps=True, language="pt")
        segments = result.get('segments', [])
        
        # 1. Identificação do tempo das mídias pelos pontos finais das frases
        sentence_end_times = []
        all_words = []
        
        for segment in segments:
            for word_info in segment.get('words', []):
                all_words.append(word_info)
                word_text = word_info['word']
                if re.search(r'[\.\!\?]', word_text):
                    sentence_end_times.append(word_info['end'])
        
        if not sentence_end_times:
            if segments:
                sentence_end_times = [seg['end'] for seg in segments]
            else:
                sentence_end_times = [result.get('duration', 10.0)]
                
        media_timings = []
        prev_time = 0.0
        for idx, end_t in enumerate(sentence_end_times):
            duration = round(end_t - prev_time, 2)
            if duration < 1.0:
                duration = 1.0
            media_timings.append({
                "midia": f"MIDIA {idx + 1}",
                "duration_seconds": duration,
                "end_timestamp": round(end_t, 2)
            })
            prev_time = end_t

        # 2. Processamento das legendas agrupadas pelo número exato de palavras
        transcription_data = []
        if legenda_option == 'incluido':
            current_group = []
            for word_info in all_words:
                current_group.append(word_info)
                if len(current_group) >= words_per_group:
                    start_time = current_group[0]['start']
                    minutes = int(start_time // 60)
                    seconds = int(start_time % 60)
                    timestamp_str = f"{minutes:02d}:{seconds:02d}"
                    text_str = " ".join([w['word'].strip() for w in current_group])
                    
                    transcription_data.append({
                        "timestamp": timestamp_str,
                        "start_seconds": round(start_time, 2),
                        "end_seconds": round(current_group[-1]['end'], 2),
                        "text": text_str
                    })
                    current_group = []
            
            if current_group:
                start_time = current_group[0]['start']
                minutes = int(start_time // 60)
                seconds = int(start_time % 60)
                timestamp_str = f"{minutes:02d}:{seconds:02d}"
                text_str = " ".join([w['word'].strip() for w in current_group])
                transcription_data.append({
                    "timestamp": timestamp_str,
                    "start_seconds": round(start_time, 2),
                    "end_seconds": round(current_group[-1]['end'], 2),
                    "text": text_str
                })

        # Retorno idêntico ao exigido no PDF do projeto
        return jsonify({
            "status": "success",
            "total_duration": round(result.get('duration', 0.0), 2),
            "media_timings": media_timings,
            "legenda_incluida": legenda_option == 'incluido',
            "transcription": transcription_data if legenda_option == 'incluido' else None
        }), 200

    except Exception as e:
        return jsonify({"status": "error", "message": f"Erro no processamento do áudio: {str(e)}"}), 500
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port)
