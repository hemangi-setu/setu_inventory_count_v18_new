/** @odoo-module **/

import { registry } from "@web/core/registry";
import { standardFieldProps } from "@web/views/fields/standard_field_props";
import { useBus, useService } from "@web/core/utils/hooks";
import * as BarcodeScanner from "@web/core/barcode/barcode_dialog";
import { Component, xml } from "@odoo/owl";
import { charField, CharField } from "@web/views/fields/char/char_field";
import { _t } from "@web/core/l10n/translation";

export class SetuBarcodeHandlerField extends CharField {

    static props = {
        ...CharField.props,

        canScanBarcode: { type: Boolean, optional: true },
    };

    setup() {
        super.setup();
        const barcode = useService("barcode");
        this.orm = useService("orm");
        this.actionService = useService("action");
        this.barcodeService = useService("barcode");
    }

    async openMobileScanner() {
        const barcode = await BarcodeScanner.scanBarcode(this.env);

        if (barcode) {
            this.barcodeService.bus.trigger('barcode_scanned', { barcode });
            if ('vibrate' in window.navigator) {
                window.navigator.vibrate(100);
            }
        } else {
            this.env.services.notification.add(_t("Please, Scan again!"), {
                type: 'warning'
            });
        }
    }
}

SetuBarcodeHandlerField.template = "setu_inventory_count_management.MobileBarcodeField";

export const setubarcodeHandlerField = {
    ...charField,
    displayName: _t("SetuBarcodeHandlerField"),
    component: SetuBarcodeHandlerField,

    extractProps() {

        return{ canScanBarcode : true };
    },
    supportedTypes: ["char"],
};

/* Register the widget only for char fields */
registry.category("fields").add("setu_barcode_handler", setubarcodeHandlerField);
