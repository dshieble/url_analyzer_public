STEALTH_INIT_SCRIPT = """
// Disabling WebDriver property
Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

// Overwriting the user agent to avoid detection
const originalUserAgent = navigator.userAgent;
Object.defineProperty(navigator, 'userAgent', {get: () => originalUserAgent.replace('HeadlessChrome', 'Chrome')});

// Mocking the plugins property
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

// Mocking the languages property
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// Mocking the hardwareConcurrency property
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => 4
});
"""

# STEALTH_INIT_SCRIPT = """
# // Disabling WebDriver property
# Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

# // Overwriting the user agent to avoid detection
# const originalUserAgent = navigator.userAgent;
# Object.defineProperty(navigator, 'userAgent', {get: () => originalUserAgent.replace('HeadlessChrome', 'Chrome')});

# // Mocking the plugins property
# Object.defineProperty(navigator, 'plugins', {
#     get: () => [1, 2, 3, 4, 5]
# });

# // Mocking the languages property
# Object.defineProperty(navigator, 'languages', {
#     get: () => ['en-US', 'en']
# });

# // Mocking the hardwareConcurrency property
# Object.defineProperty(navigator, 'hardwareConcurrency', {
#     get: () => 4
# });
# """

STEALTH_INIT_SCRIPT_OLD = """
Object.defineProperty(Navigator.prototype, 'webdriver', {
    set: undefined,
    enumerable: true,
    configurable: true,
    get: new Proxy(
        Object.getOwnPropertyDescriptor(Navigator.prototype, 'webdriver').get,
        { apply: (target, thisArg, args) => {
            // emulate getter call validation
            Reflect.apply(target, thisArg, args);
            return false;
        }}
    )
});
"""