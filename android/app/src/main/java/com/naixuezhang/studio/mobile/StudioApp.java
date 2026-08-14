package com.naixuezhang.studio.mobile;

import android.app.Application;
import android.util.Log;

public class StudioApp extends Application {
    private LocalStudioServer server;
    private int port = 18797;

    @Override
    public void onCreate() {
        super.onCreate();
        server = new LocalStudioServer(this);
        try {
            port = server.start();
        } catch (Exception error) {
            Log.e("NaiPhone", "local server failed", error);
        }
    }

    public int getPort() {
        return port;
    }
}
