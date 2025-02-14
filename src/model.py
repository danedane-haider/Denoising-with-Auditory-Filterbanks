import torch
import torch.nn as nn
from torchaudio.transforms import InverseSpectrogram, Spectrogram

from hybra import AudletFIR

class NSNet(nn.Module):
    def __init__(self):
        super().__init__()

        GRU_size = 400
        num_channels = 40

        self.linear_before = nn.Linear(num_channels, GRU_size)

        self.gru = nn.GRU(
            input_size=GRU_size,
            hidden_size=GRU_size,
            num_layers=2,
            batch_first=True,
        )

        self.linear_after = nn.Linear(GRU_size, 600)
        self.linear_after2 = nn.Linear(600, 600)
        self.linear_after3 = nn.Linear(600, num_channels)


    def forward(self, x):

        x = x.permute(0, 2, 1)
        x = torch.relu(self.linear_before(x))
        x, _ = self.gru(x)
        x = torch.relu(self.linear_after(x))
        x = torch.relu(self.linear_after2(x))
        x = torch.sigmoid(self.linear_after3(x))
        x = x.permute(0, 2, 1)

        return x

class AUDModel(nn.Module):
    def __init__(self):
        super().__init__()

        config = {
            "filter_len": 128,
            "num_channels": 40,
            "fs": 16000,
            "Ls": 5*16000,
            "bwmul": 1,
        }
        self.nsnet = NSNet()
        self.filterbank = AudletFIR(filterbank_config=config, use_decoder=True)

    def forward(self, x):
        x = self.filterbank(x)
        mask = self.nsnet(torch.log10(torch.max(x.abs()**2, 1e-8 * torch.ones_like(x, dtype=torch.float32))))
        x_real = mask * x.real
        x_imag = mask * x.imag

        return self.filterbank.decoder(x_real, x_imag)

class FFTModel(nn.Module):
    def __init__(self, fs=16000, signal_length=5):
        super().__init__()

        self.fs = fs
        self.signal_length = signal_length

        self.nsnet = NSNet()
        self.specgram = Spectrogram(
            n_fft=512, win_length=512, hop_length=256, power=None
        )
        self.power_specgram = Spectrogram(
            n_fft=512, win_length=512, hop_length=256, power=2
        )
        self.inverse_specgram = InverseSpectrogram(
            n_fft=512, win_length=512, hop_length=256
        )
    
    def forward(self, x):
        self.specgram = self.specgram.to(x.device)
        self.power_specgram: Spectrogram = self.power_specgram.to(x.device)
        self.inverse_specgram = self.inverse_specgram.to(x.device)

        x_fft = self.specgram(x)
        x = torch.log10(
            torch.max(
                self.power_specgram(x),
                torch.ones(
                    x.shape[0],
                    257,
                    self.fs * self.signal_length // 255,
                    dtype=torch.float32,
                ).to(x.device)
                * 1e-6,
            )
        )[:, :-1, :]
        x = self.nsnet(x)

        x = (
        torch.cat(
                [
                    torch.ones(x.shape[0], 1, x.shape[2]).to(x.device),
                    x,
                ],
                axis=1,
            )
            * x_fft
        )

        return self.inverse_specgram(x)
