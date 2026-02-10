package com.signage.watchdog;

import android.Manifest;
import android.content.Intent;
import android.content.SharedPreferences;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.widget.Button;
import android.widget.Toast;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.content.ContextCompat;

/**
 * Launcher activity to configure permissions and start the watchdog.
 */
public class ConfigActivity extends AppCompatActivity {
    private static final int NOTIFICATION_PERMISSION_REQUEST = 100;
    private static final int LAUNCH_DELAY_MS = 5_000;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_config);
        requestBatteryOptimizationExemption();

        Button btnUsage = findViewById(R.id.btn_usage_access);
        btnUsage.setOnClickListener(v -> {
            startActivity(new Intent(Settings.ACTION_USAGE_ACCESS_SETTINGS));
            Toast.makeText(this, "Enable 'Signage Watchdog' usage access", Toast.LENGTH_LONG).show();
        });

        Button btnOverlay = findViewById(R.id.btn_overlay_permission);
        btnOverlay.setOnClickListener(v -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                Intent intent = new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                    Uri.parse("package:" + getPackageName()));
                startActivity(intent);
            } else {
                Toast.makeText(this, "Overlay permission not required", Toast.LENGTH_SHORT).show();
            }
        });

        Button btnStart = findViewById(R.id.btn_start_watchdog);
        btnStart.setOnClickListener(v -> {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M && !Settings.canDrawOverlays(this)) {
                Toast.makeText(this, "Grant Overlay Permission (Step 2) first!", Toast.LENGTH_LONG).show();
                return;
            }
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.LOLLIPOP && !WatchdogService.hasUsageStatsPermission(this)) {
                Toast.makeText(this, "Grant Usage Access (Step 1) first!", Toast.LENGTH_LONG).show();
                return;
            }

            requestNotificationPermission();
            startWatchdog();

            btnStart.setEnabled(false);
            btnStart.setText("Watchdog Active...");
            Toast.makeText(this, "Starting signage player...", Toast.LENGTH_SHORT).show();

            new Handler(Looper.getMainLooper()).postDelayed(() -> {
                startActivity(new Intent(this, LaunchTrampolineActivity.class));
                finish();
            }, LAUNCH_DELAY_MS);
        });
    }

    private void requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
                requestPermissions(new String[]{Manifest.permission.POST_NOTIFICATIONS},
                    NOTIFICATION_PERMISSION_REQUEST);
            }
        }
    }

    private void requestBatteryOptimizationExemption() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return;
        SharedPreferences prefs = getSharedPreferences("watchdog_prefs", MODE_PRIVATE);
        if (prefs.getBoolean("battery_prompt_shown", false)) return;
        PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
        if (pm == null || pm.isIgnoringBatteryOptimizations(getPackageName())) return;
        try {
            prefs.edit().putBoolean("battery_prompt_shown", true).apply();
            Intent intent = new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                Uri.parse("package:" + getPackageName()));
            startActivity(intent);
        } catch (Exception ignored) { }
    }

    private void startWatchdog() {
        Intent intent = new Intent(this, WatchdogService.class);
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            startForegroundService(intent);
        } else {
            startService(intent);
        }
    }
}
