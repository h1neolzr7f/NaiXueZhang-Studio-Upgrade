package com.naixuezhang.studio.mobile;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;

import java.net.HttpURLConnection;
import java.net.URL;

public class SplashActivity extends Activity {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private long startedAt;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_splash);
        startedAt = System.currentTimeMillis();
        waitForLocalServer(0);
    }

    private void waitForLocalServer(int attempt) {
        if (isFinishing()) return;
        new Thread(() -> {
            boolean ok = probe();
            handler.post(() -> {
                if (isFinishing()) return;
                long elapsed = System.currentTimeMillis() - startedAt;
                if (ok && elapsed >= 700) {
                    goMain();
                    return;
                }
                if (attempt >= 24) {
                    goMain();
                    return;
                }
                handler.postDelayed(() -> waitForLocalServer(attempt + 1), 250);
            });
        }, "nai-wait-server").start();
    }

    private boolean probe() {
        int port = 18797;
        if (getApplication() instanceof StudioApp) {
            StudioApp app = (StudioApp) getApplication();
            if (!app.isReady()) return false;
            port = app.getPort();
        }
        HttpURLConnection conn = null;
        try {
            conn = (HttpURLConnection) new URL("http://127.0.0.1:" + port + "/api/mobile/status").openConnection();
            conn.setConnectTimeout(400);
            conn.setReadTimeout(400);
            conn.setUseCaches(false);
            conn.setRequestMethod("GET");
            return conn.getResponseCode() == 200;
        } catch (Exception ignored) {
            return false;
        } finally {
            if (conn != null) conn.disconnect();
        }
    }

    private void goMain() {
        startActivity(new Intent(this, MainActivity.class));
        overridePendingTransition(android.R.anim.fade_in, android.R.anim.fade_out);
        finish();
    }
}
