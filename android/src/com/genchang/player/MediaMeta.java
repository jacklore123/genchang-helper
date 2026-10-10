package com.genchang.player;

import android.media.MediaMetadataRetriever;

import java.io.File;

/** 用系统解码器读音频时长。 */
public class MediaMeta {
    public static long durationMs(File f) {
        MediaMetadataRetriever r = new MediaMetadataRetriever();
        try {
            r.setDataSource(f.getAbsolutePath());
            String d = r.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION);
            if (d != null) return Long.parseLong(d);
        } catch (Exception ignored) {
        } finally {
            try { r.release(); } catch (Exception ignored) {}
        }
        return 0;
    }
}
