import { test, expect } from '@playwright/test';

// Use desktop viewport for all tests
test.use({ viewport: { width: 1280, height: 800 } });

test.describe('Trading Dashboard - Core Layout', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000); // Wait for hydration
    });

    test('should load the main dashboard without errors', async ({ page }) => {
        // Check main layout elements exist
        await expect(page.locator('header').first()).toBeVisible();
        await expect(page.locator('body')).toBeVisible();
    });

    test('should display trading chart area', async ({ page }) => {
        // Check chart container exists - look for canvas or chart div
        const chartArea = page.locator('canvas, [class*="chart"]').first();
        await expect(chartArea).toBeVisible({ timeout: 15000 });
    });

    test('should display symbol BTCUSDT', async ({ page }) => {
        await expect(page.getByText('BTCUSDT').first()).toBeVisible();
    });

    test('should display positions and orders tabs', async ({ page }) => {
        await expect(page.getByText('Positions').first()).toBeVisible();
        await expect(page.getByText('Orders').first()).toBeVisible();
    });

    test('should have Strategy panel with Edit button', async ({ page }) => {
        // Check strategy section by heading text
        await expect(page.getByRole('heading', { name: /Strategy/i }).first()).toBeVisible();

        // Check for Edit button
        const editButton = page.locator('button:has-text("Edit")').first();
        await expect(editButton).toBeVisible();
    });

    test('should have Health panel', async ({ page }) => {
        await expect(page.getByRole('heading', { name: /Health/i }).first()).toBeVisible();
    });

    test('should have Account panel', async ({ page }) => {
        await expect(page.getByRole('heading', { name: /Account/i }).first()).toBeVisible();
    });

    test('should have Manual Trade panel', async ({ page }) => {
        await expect(page.getByRole('heading', { name: /Manual Trade/i }).first()).toBeVisible();
    });

    test('should have BOT button', async ({ page }) => {
        const botButton = page.locator('button:has-text("BOT")').first();
        await expect(botButton).toBeVisible();
    });
});

test.describe('Trading Dashboard - Interactions', () => {
    test.beforeEach(async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000);
    });

    test('should be able to click Edit button', async ({ page }) => {
        const editButton = page.locator('button:has-text("Edit")').first();
        await editButton.click();
        await page.waitForTimeout(1000);

        // Some modal/overlay should appear
        const overlay = page.locator('.fixed').first();
        expect(await overlay.count()).toBeGreaterThan(0);
    });

    test('should be able to click BOT button', async ({ page }) => {
        const botButton = page.locator('button:has-text("BOT")').first();
        await botButton.click();
        await page.waitForTimeout(500);

        // Page should still be functional
        await expect(page.locator('body')).toBeVisible();
    });

    test('Escape key should not crash the page', async ({ page }) => {
        await page.keyboard.press('Escape');
        await expect(page.locator('body')).toBeVisible();
    });

    test('Ctrl+Space should not crash the page', async ({ page }) => {
        await page.keyboard.press('Control+Space');
        await page.waitForTimeout(500);
        await expect(page.locator('body')).toBeVisible();
    });
});

test.describe('Navigation', () => {
    test('Strategy Studio link should exist in header', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000);

        // Check the link exists (even if possibly hidden on some viewports)
        const strategyLink = page.locator('a[href="/strategy-studio"]').first();
        expect(await strategyLink.count()).toBeGreaterThan(0);
    });

    test('Strategy Studio page should load', async ({ page }) => {
        await page.goto('/strategy-studio');
        await page.waitForTimeout(2000);

        // Page should load without crash
        await expect(page.locator('body')).toBeVisible();
    });

    test('Home page (Trading Desk) should load', async ({ page }) => {
        await page.goto('/');
        await expect(page).toHaveURL('/');
    });
});

test.describe('Error Handling', () => {
    test('should handle page load without JS errors', async ({ page }) => {
        const errors: string[] = [];
        page.on('pageerror', (error) => {
            errors.push(error.message);
        });

        await page.goto('/');
        await page.waitForTimeout(3000);

        // Filter out expected network errors (API/WebSocket may not be running)
        const unexpectedErrors = errors.filter(e =>
            !e.includes('WebSocket') &&
            !e.includes('fetch') &&
            !e.includes('Failed to fetch') &&
            !e.includes('NetworkError') &&
            !e.includes('ERR_CONNECTION_REFUSED')
        );

        expect(unexpectedErrors).toHaveLength(0);
    });
});

test.describe('Visual Screenshots', () => {
    test('capture desktop layout', async ({ page }) => {
        await page.setViewportSize({ width: 1920, height: 1080 });
        await page.goto('/');
        await page.waitForTimeout(3000);

        await page.screenshot({ path: 'e2e/screenshots/desktop-full.png', fullPage: true });
        await expect(page.locator('body')).toBeVisible();
    });
});
