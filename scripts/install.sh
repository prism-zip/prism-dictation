echo & echo "🤖 Installing software"

sudo apt install pulseaudio-utils xdotool git wget zip -y 
pip3 install vosk
wget https://alphacephei.com/kaldi/models/vosk-model-en-us-0.22.zip
unzip vosk-model-en-us-0.22.zip
mv vosk-model-en-us-0.22 model
mkdir -p ~/.config/prism-dictation

echo & echo "✨ Done ✨"