import type { GlobalThemeOverrides } from "naive-ui";

export const themeOverrides: GlobalThemeOverrides = {
  common: {
    primaryColor: "#397EEC",
    primaryColorHover: "#4B8CF2",
    primaryColorPressed: "#2B69CF",
    primaryColorSuppl: "#025BFE",
    borderRadius: "12px",
    fontFamily: '"Outfit", "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif',
  },
  Button: {
    borderRadiusMedium: "12px",
    fontWeightStrong: "600",
  },
  Menu: {
    itemHeight: "38px",
    borderRadius: "10px",
    itemColorActive: "#EAF2FE",
    itemColorActiveHover: "#E4EEFE",
    itemTextColorActive: "#397EEC",
    itemIconColorActive: "#397EEC",
  },
};
