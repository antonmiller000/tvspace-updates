package app.tgfinder;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;

import com.chaquo.python.PyObject;
import com.chaquo.python.Python;
import com.chaquo.python.android.AndroidPlatform;

import java.io.File;

/** Keeps the search engine (Python) alive while the screen is off or the app is in the background. */
public class FinderService extends Service {
    static final int PORT = 8765;
    static final String ACTION_QUIT = "app.tgfinder.QUIT";
    private static final String CHANNEL = "finder";

    private final Handler handler = new Handler(Looper.getMainLooper());
    private PowerManager.WakeLock wakeLock;
    private volatile PyObject module;

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = getSystemService(NotificationManager.class);
        if (Build.VERSION.SDK_INT >= 26) {
            nm.createNotificationChannel(new NotificationChannel(CHANNEL, "Search engine", NotificationManager.IMPORTANCE_LOW));
        }
        Notification n = notification("Ready");
        if (Build.VERSION.SDK_INT >= 29) {
            startForeground(1, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC);
        } else {
            startForeground(1, n);
        }
        wakeLock = ((PowerManager) getSystemService(POWER_SERVICE)).newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "tgfinder:search");
        wakeLock.setReferenceCounted(false);

        new Thread(() -> {
            if (!Python.isStarted()) Python.start(new AndroidPlatform(getApplicationContext()));
            File data = new File(getFilesDir(), "data");
            data.mkdirs();
            PyObject m = Python.getInstance().getModule("tgfinder.android");
            m.callAttr("start", data.getAbsolutePath(), PORT);
            module = m;
        }, "python-start").start();
        handler.postDelayed(this::tick, 5000);
    }

    /** Hold the CPU awake only while a search is actually running. */
    private void tick() {
        PyObject m = module;
        if (m != null) {
            new Thread(() -> {
                boolean busy;
                try {
                    busy = m.callAttr("busy").toBoolean();
                } catch (Exception e) {
                    busy = false;
                }
                final boolean b = busy;
                handler.post(() -> {
                    if (b && !wakeLock.isHeld()) wakeLock.acquire();
                    if (!b && wakeLock.isHeld()) wakeLock.release();
                    getSystemService(NotificationManager.class).notify(1, notification(b ? "Searching…" : "Ready"));
                });
            }).start();
        }
        handler.postDelayed(this::tick, 15000);
    }

    private Notification notification(String text) {
        int flags = PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE;
        PendingIntent open = PendingIntent.getActivity(this, 0, new Intent(this, MainActivity.class), flags);
        PendingIntent quit = PendingIntent.getService(this, 1, new Intent(this, FinderService.class).setAction(ACTION_QUIT), flags);
        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CHANNEL) : new Notification.Builder(this);
        return b.setSmallIcon(R.drawable.ic_stat)
                .setContentTitle("Telegram Finder")
                .setContentText(text)
                .setContentIntent(open)
                .setOngoing(true)
                .setOnlyAlertOnce(true)
                .addAction(new Notification.Action.Builder(null, "Quit", quit).build())
                .build();
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        if (intent != null && ACTION_QUIT.equals(intent.getAction())) {
            quit(this);
        }
        return START_STICKY;
    }

    static void quit(Service s) {
        s.stopForeground(true);
        s.stopSelf();
        // The embedded Python runtime cannot be shut down cleanly; end the process.
        android.os.Process.killProcess(android.os.Process.myPid());
    }

    @Override
    public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (wakeLock != null && wakeLock.isHeld()) wakeLock.release();
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) {
        return null;
    }
}
