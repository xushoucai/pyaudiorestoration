import numpy as np
import soundfile as sf
import matplotlib.pyplot as plt
from scipy.signal import butter, sosfiltfilt
import sys
import os

def butter_bandpass(lowcut, highcut, fs, order=5):
	nyq = 0.5 * fs
	low = lowcut / nyq
	high = highcut / nyq
	sos = butter(order, [low, high], analog=False, btype='band', output='sos')
	return sos

def butter_bandpass_filter(data, lowcut, highcut, fs, order=5):
	sos = butter_bandpass(lowcut, highcut, fs, order=order)
	y = sosfiltfilt(sos, data)
	return y
  
def rms(a):
	return np.sqrt(np.mean(np.square(a)))

def windowed_rms(signal, hop, sz):
	out = []
	for i in range(0, len(signal), hop):
		win = signal[i:i+sz]
		# hann = np.hanning(len(win))
		# out.append(rms(win*hann))
		out.append(rms(win))
	return np.asarray(out)

def process(filename_src, filename_ref):
	sound_obs = []
	for filename in (filename_src, filename_ref):
		#make sure they exist
		if not os.path.isfile(filename):
			print(filename+" does not exist! Make sure its file path is correct!")
			return
	
		#make sure they can be read
		try:
			sound_obs.append( sf.SoundFile(filename) )
		except RuntimeError as e:
			print(e)
			return
		
	#hop & sample size for the windowed rms
	hop = 32
	sz = 512
	#number of volume samples to use for each alignment step
	#increase this if the sources are badly out of sync
	corr_sz = 4096
	#optimum for the hann window
	corr_hop = corr_sz // 2

	#frequencies for the bandpass filter
	lower = 400 #Hz
	upper = 4000 #Hz
	
	signal_src = sound_obs[0].read(always_2d=True, dtype='float32')
	signal_ref = sound_obs[1].read(always_2d=True, dtype='float32')
	
	if sound_obs[0].samplerate != sound_obs[1].samplerate:
		print("Both files must have the same sample rate!")
		return
	if sound_obs[0].channels != sound_obs[1].channels:
		print("Both files must have the same amount of channels!")
		return
	if len(signal_src[:,0]) != len(signal_ref[:,0]):
		print("Both files must have the same amount of samples!")
		return
		
	sr = sound_obs[0].samplerate
	#create empty output array
	out = np.empty( signal_src.shape )
	hann = np.hanning( corr_sz )
	#go over all channels
	for channel in range(sound_obs[0].channels):
		print("Matching channel",channel)
		#bandpass both to avoid distortion and vinyl rumble
		signal_src_c = butter_bandpass_filter(signal_src[:,channel], lower, upper, sr, order=3)
		signal_ref_c = butter_bandpass_filter(signal_ref[:,channel], lower, upper, sr, order=3)
		
		#get rms for source & ref
		rms_src = windowed_rms(signal_src_c, hop, sz)
		rms_ref = windowed_rms(signal_ref_c, hop, sz)
		
		#pad both so we can window over the ends later
		rms_src_padded = np.pad(rms_src, (corr_hop, corr_hop*2), "edge")
		rms_ref_padded = np.pad(rms_ref, (corr_hop, corr_hop*2), "edge")
		
		rms_src_aligned = np.zeros( rms_src_padded.shape )
		offsets = []
		vals = []
		for x in range(corr_hop, len(rms_src), corr_hop):
			# print(x-corr_hop,x+corr_hop)
			rms_ref_win = rms_ref_padded[x-corr_hop:x+corr_hop] * hann
			rms_src_win = rms_src_padded[x-corr_hop:x+corr_hop] * hann
			
			# cross-correlate to get the offset
			res = np.correlate(rms_ref_win, rms_src_win, mode="same")
			val = np.max(res)
			vals.append(val)
			# check if there was enough signal power for a reliable correlation
			if val > 0.1:
				offset = np.argmax(res) - len(res)//2
			else:
				if offsets:
					offset = offsets[-1]
				else:
					offset = 0
			offsets.append(offset)
			
			# reconstruct signal with offset for this windowed segment
			rms_src_aligned[x-corr_hop:x+corr_hop] += np.roll(rms_src_win, offset)
		
		#remove the padding from start and end of the aligned rms
		rms_src_aligned = rms_src_aligned[corr_hop:-corr_hop*2]
			
		# plt.figure()
		# # plt.plot(offsets, label="offsets")
		# # plt.plot(vals, label="vals")
		# plt.plot(rms_src_padded, label="rms_src_padded")
		# plt.plot(rms_ref_padded, label="rms_ref_padded")
		# plt.xlabel('Time')
		# plt.ylabel('RMS')
		# plt.legend(frameon=True, framealpha=0.75)
		# plt.show()
		# break
		
		#calculate factors
		fac_aligned = rms_ref/rms_src_aligned
		
		# clip to truncate outliers
		np.clip(fac_aligned, 0, 2, fac_aligned)
		#replace nans caused by zero volume in src
		np.nan_to_num(fac_aligned, copy=False)
		
		# interpolate over whole signal
		fac_interp = np.interp( np.arange( len(signal_src)), np.arange(0, len(signal_src), hop), fac_aligned  )
		#write channel to output
		out[:,channel] = signal_src[:,channel] *fac_interp
		
		# plt.figure()
		# plt.plot(rms_ref, label="ref")
		# plt.plot(rms_src, label="src")
		# plt.plot(rms_src_aligned, label="rms_src_aligned")
		# plt.plot(fac, label="fac")
		# plt.plot(fac_aligned, label="fac_aligned")
		# plt.xlabel('Time')
		# plt.ylabel('RMS')
		# plt.legend(frameon=True, framealpha=0.75)
		# plt.show()
		# break
	#write wav
	print("Writing output")
	sf.write(filename_src+'decompressed.wav', out, sr, subtype='FLOAT')
	
if __name__ == "__main__":
	if len(sys.argv) != 3:
		print("Script has to be called like this: python rms.py [FILE_YOU_WANT_TO_RESTORE] [FILE_WITH_INTENDED_DYNAMICS]")
		print('eg.: python rms.py "C:/All Things Must Pass [2001 Remaster - Disc 1]/01 Id Have You Anytime.flac" "C:/All Things Must Pass [2010 Reissue]/01 Id Have You Anytime.flac"')
	else:
		process(sys.argv[1], sys.argv[2])