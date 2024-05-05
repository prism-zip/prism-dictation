echo & echo "Install software..."
echo & echo "created by:  ideasman42"

echo & echo "Install pulse audio utils and xdotool"
sudo apt install pulseaudio-utils xdotool git wget zip -y

pip3 install vosk
git clone https://github.com/prism-zip/prism-dictation.git
cd prism-dictation
wget https://alphacephei.com/kaldi/models/vosk-model-en-us-0.22.zip
unzip vosk-model-en-us-0.22.zip
mv vosk-model-en-us-0.22 model


