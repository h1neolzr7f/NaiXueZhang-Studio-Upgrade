package com.naixuezhang.studio.mobile;

import android.app.Application;
import android.util.Log;

public class StudioApp extends Application {
    private LocalStudioServer server;
    private int port = 18797;
    private volatile boolean ready = false;

    @Override
    public void onCreate() {
        super.onCreate();
        server = new LocalStudioServer(this);
        try {
            port = server.start();
            ready = port > 0;
        } catch (Exception error) {
            ready = false;
            Log.e("NaiPhone", "local server failed", error);
        }
    }

    public int getPort() {
        return port;
    }

    public boolean isReady() {
        return ready && server != null && server.getPort() > 0;
    }
}
